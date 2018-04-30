##############################################################################
#
# Copyright (C) Zenoss, Inc. 2014-2018, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

from collections import defaultdict
from itertools import chain, izip
from functools import partial
from pprint import pformat
import logging
import time
import traceback
import pickle

from twisted.internet.defer import inlineCallbacks, returnValue

from Products import Zuul
from Products.ZenEvents import ZenEventClasses
from Products.ZenModel.DeviceComponent import DeviceComponent
from Products.ZenUtils.Utils import monkeypatch
from Products.Zuul import IInfo

from ZenPacks.zenoss.PythonCollector.datasources.PythonDataSource \
    import PythonDataSourcePlugin

from ZenPacks.zenoss.CalculatedPerformance import operations
from ZenPacks.zenoss.CalculatedPerformance.AggregatingDataPoint \
    import AggregatingDataPoint
from ZenPacks.zenoss.CalculatedPerformance.ReadThroughCache \
    import getReadThroughCache
from ZenPacks.zenoss.CalculatedPerformance.utils import (
    toposort, grouper, dotTraverse, getVarNames, createDeviceDictionary,
    get_ds_key, async_timeit, ContextLogAdapter)


LOG = logging.getLogger('zen.CalculatedPerformance.dsplugins')


RRD_READ_CHUNKS = 20
# Map for lists of current values pre-aggregation, used to
# decorate threshold violation events
#
# key: 'deviceid_componentid_eventKey'
# value: map of target dev/component uuid + event key to
#        last values (or deviation values) used for aggregation
THRESHOLD_CACHE = {}


def getThresholdCacheKey(datasource, datapoint):
    return '{device}_{component}_{datasource}_{datapoint}'.format(
        device=datasource.device,
        component=datasource.component,
        datasource=datasource.datasource,
        datapoint=datapoint.id)


def getExtraTargets(extraContexts, context):
    """
    For each path in extraContexts, this retrieves:
      1) the enclosing device (for path 'device')
      2) the other end of a ToOneRelationship
      3) a component in a ToManyContRelationship, by id or index
      4) either 2 or 3, but starting from the device containing the context,
           if the path begins 'device/' and the context is a component

    """
    targets = []

    for path in extraContexts:
        if path == 'device':
            targets.append(context.device())
            continue

        logPreamble = (
            "While looking for an extraContext "
            "for '{context_id}' using path '{path}',".format(
                context_id=context.id, path=path))

        log_warn = partial(LOG.warn, "%s %s", logPreamble)

        devPrefix = 'device/'
        pathContext = context.device() if path.startswith(devPrefix) else context
        relativePath = path[len(devPrefix):] if path.startswith(devPrefix) else path

        toOneRels = [
            r for r in pathContext.objectValues(spec=('ToOneRelationship',))
            if r.id == relativePath]

        if toOneRels:
            target = toOneRels[0]()
            if target:
                targets.append(target)
            else:
                log_warn(
                    "relativePath '%s' led to an empty ToOne relationship "
                    "on pathContext '%s', skipping.",
                    relativePath, pathContext.id)
            continue

        if relativePath.count('/') != 1:
            log_warn(
                "relativePath '%s' does not lead to a ToOne relationship or "
                "an item in a ToManyContains relationship, skipping.",
                relativePath)
            continue

        relname, extraId = relativePath.split('/')
        rels = [
            r for r in pathContext.objectValues(spec=('ToManyContRelationship',))
            if r.id == relname]

        if not rels:
            log_warn(
                "The relname '%s' in relativePath '%s' "
                "does not exist on pathContext '%s', skipping.",
                relname, relativePath, pathContext.id)
            continue

        rel = rels[0]

        extraTarget = getattr(rel, extraId, None)

        if extraTarget:
            targets.append(extraTarget)
            continue

        if extraId.isdigit():
            index = int(extraId)
            if index < len(rel()):
                extraTarget = rel()[index]
                targets.append(extraTarget)
            else:
                log_warn(
                    "The contents of relationship '%s' on context '%s' "
                    "is too short to get member '%s', skipping'",
                    relname, pathContext.id, extraId)
        else:
            log_warn(
                "The extraId '%s' in relativePath '%s' does not exist "
                "on the relationship '%s' on '%s', skipping.",
                extraId, relativePath, relname, pathContext.id)

    return targets


def dsDescription(ds, devdict):
    return (
        "expression: {expression} "
        "dictionary: {dictionary} "
        "context device: {device} "
        "context component: {component} "
        "template: {template} "
        "datasource: {datasource} "
        "datapoint: {datapoint}".format(
            expression=ds.params.get('expression', None),
            dictionary=pformat(devdict),
            device=ds.device,
            component=ds.component or '',
            template=ds.params.get('template', None),
            datasource=ds.datasource,
            datapoint=ds.points[0].id))


def targetInfo(target):
    """
    Return a suitable target dictionary for Aggregate
    and Calculated target elements.

    Includes: uuid, name, uid, id, rrdpath, device

    """
    targetConfig = Zuul.marshal(IInfo(target), keys=('uuid', 'name', 'id'))
    targetConfig['rrdpath'] = target.rrdPath()
    if isinstance(target, DeviceComponent):
        targetConfig['device'] = targetInfo(target.device())
    return targetConfig


def handleArguments(targetArgValues, dpargs):
    tokens = dpargs.strip().split(',') if dpargs.strip() else []
    arguments = []
    for tok, x in izip(tokens, range(len(tokens))):
        arguments.append(
            targetArgValues[x] if getVarNames(tok) else tok.strip())

    return arguments


class AggregatingDataSourcePlugin(object):

    @classmethod
    def params(cls, datasource, context):
        targetInfos = []
        # Add an id->contents map for each component/device.
        for member in dotTraverse(context, datasource.targetMethod or '') or []:
            targetInfos.append(targetInfo(member))

        targetArgValues = []
        for datapoint in datasource.datapoints():
            if isinstance(datapoint, AggregatingDataPoint):
                for att in getVarNames(datapoint.arguments.strip()):
                    targetArgValues.append(dotTraverse(context, att))
            else:
                LOG.error(
                    "Datasource %s has a datapoint of the wrong type %s",
                    datasource, datapoint)

            # should be only datapoint, so ...
            break

        zDebug = context.getZ('zDatasourceDebugLogging')
        return dict(
            targetDatapoints=[(
                datasource.targetDataSource,
                datasource.targetDataPoint,
                datasource.targetRRA or 'AVERAGE',
                datasource.targetAsRate,
                targetInfos)],
            targetArgValues=[tuple(targetArgValues)],
            debug=datasource.debug or zDebug)

    @inlineCallbacks
    def collect(self, config, datasource, rrdcache, collectionTime):
        collectedEvents = []
        collectedValues = {}
        data = {}
        debug = datasource.params.get('debug', None)

        # Aggregate datasources only have one target datapoint config.
        targetDatasource, targetDatapoint, targetRRA, targetAsRate, targets = datasource.params['targetDatapoints'][0]

        targetValues, errors = yield self.getLastValues(
            rrdcache, targetDatasource, targetDatapoint, targetRRA,
            targetAsRate, datasource.cycletime*5, targets)

        logMethod = LOG.error if debug else LOG.debug
        for ex, msg in errors:
            logMethod('%s: %s', msg, ex)

        if not targetValues:
            if targets:
                msg = "No target values collected for datasource {ds_key}".format(
                    ds_key=get_ds_key(datasource))

                severity = ZenEventClasses.Info if debug else ZenEventClasses.Debug

                collectedEvents.append({
                    'summary': msg,
                    'eventKey': 'aggregatingDataSourcePlugin_novalues',
                    'severity': severity})

                logMethod = LOG.info if debug else LOG.debug
                logMethod(msg)

            returnValue({
                'events': collectedEvents,
                'values': collectedValues})

        for datapoint in datasource.points:
            try:
                aggregate, adjustedTargetValues = yield self.performAggregation(
                    datapoint.operation,
                    handleArguments(
                        datasource.params['targetArgValues'][0],
                        datapoint.arguments),
                    targetValues)
            except AggregationError as e:
                prefix = "aggregation error for {}_{}".format(
                    targetDatasource,
                    targetDatapoint)

                collectedEvents.append({
                    'severity': ZenEventClasses.Error,
                    'summary': "{}: {}".format(prefix, e.summary),
                    'message': "{}: {}".format(prefix, e.message),
                    'eventClass': datasource.eventClass})

                continue

            if debug:
                LOG.debug(
                    "Aggregate value %s calculated for datapoint %s_%s on %s:%s",
                    str(aggregate), datasource.datasource, datapoint.id,
                    datasource.device, datasource.component)

            # Stash values for the threshold to put in event details.
            threshold_cache_key = getThresholdCacheKey(datasource, datapoint)
            THRESHOLD_CACHE[threshold_cache_key] = adjustedTargetValues

            collectedValues.setdefault(datasource.component, {})
            collectedValues[datasource.component]['_'.join(
                (datasource.datasource, datapoint.id))] = (aggregate, collectionTime)

        data['events'] = collectedEvents
        data['values'] = collectedValues

        returnValue(data)

    @inlineCallbacks
    def getLastValues(
            self, rrdcache, datasource, datapoint,
            rra='AVERAGE', rate=False, cycleTime=300, targets=()):
        values = {}
        errors = []
        for chunk in grouper(RRD_READ_CHUNKS, targets):
            chunkDict, chunkErrors = yield rrdcache.getLastValues(
                datasource, datapoint, rra, rate, cycleTime*5, chunk)

            values.update(chunkDict)
            errors.extend(chunkErrors)

        returnValue((values, errors))

    def performAggregation(self, operationId, arguments, targetValues):
        if not operationId:
            raise AggregationError(
                summary="no operation set",
                message="no operation set - set one of {}".format(
                    ", ".join(operations.VALID_OPERATIONS)))

        operationId = operationId.lower()
        if operationId not in operations.VALID_OPERATIONS:
            raise AggregationError(
                summary="{} is an invalid operation".format(operationId),
                message="{} is an invalid operation - set one of {}".format(
                    operationId,
                    ", ".join(operations.VALID_OPERATIONS)))

        try:
            return getattr(operations, operationId)(targetValues, *arguments)
        except Exception as e:
            raise AggregationError(
                summary=str(e),
                message=traceback.format_exc())


class AggregationError(Exception):

    def __init__(self, summary, message=None):
        Exception.__init__(self, summary)
        self.summary = summary
        self.message = message or summary


class CalculatedDataSourcePlugin(object):

    @classmethod
    def isPicklable(cls, object):
        try:
            pickle.dumps(object, pickle.HIGHEST_PROTOCOL)
            return True
        except:
            pass
        return False

    @classmethod
    def params(cls, datasource, context):
        zDebug = context.getZ('zDatasourceDebugLogging')
        config = {
            'expression': datasource.expression,
            'debug': datasource.debug or zDebug,
            'template': datasource.rrdTemplate().getPrimaryId()}

        attrs = {}
        targetDatapoints = {}

        # Keep track of all datapoints from all targets so we can avoid
        # looking for an attribute when we have found a datapoint by name on
        # an earlier target already.
        combinedDatapoints = {}

        # extraContents can contain paths to other objects that could have
        # metrics or attributes.
        allTargets = getExtraTargets(datasource.extraContexts, context)
        allTargets.append(context)

        # count down to the last target
        hasMore = len(allTargets)

        for target in allTargets:
            hasMore -= 1

            allDatapointsByVarName = {}
            for dp in target.getRRDDataPoints():
                allDatapointsByVarName[dp.id] = dp
                allDatapointsByVarName[dp.name()] = dp
            combinedDatapoints.update(allDatapointsByVarName)

            for att in getVarNames(datasource.expression):

                if att in allDatapointsByVarName:
                    datapoint = allDatapointsByVarName[att]
                    fqdpn = '%s_%s' % (datapoint.datasource().id, datapoint.id)
                    targetDatapoints[fqdpn] = (
                        datapoint.datasource().id,
                        datapoint.id,
                        'AVERAGE',
                        datasource.targetAsRate,
                        [targetInfo(target)])

                elif att not in combinedDatapoints:
                    value = dotTraverse(target, att)
                    if not CalculatedDataSourcePlugin.isPicklable(value):
                        LOG.error(
                            "Calculated Performance expression %s references "
                            "invalid attribute (unpicklable value) %s",
                            datasource.expression, att)
                        return config

                    # Only store None if we finished and never found
                    # a more interesting value.
                    if value is not None:
                        attrs[att] = value
                    elif att not in attrs and not hasMore:
                        attrs[att] = value
                        LOG.warn(
                            "Calculated Performance expression %s references "
                            "the variable %s which is not in %s on the targets %s",
                            datasource.expression, att,
                            combinedDatapoints.keys(), allTargets)

        config['obj_attrs'] = attrs
        config['targetDatapoints'] = targetDatapoints.values()

        return config

    @inlineCallbacks
    def collect(self, config, datasource, rrdcache, collectionTime):
        collectedEvents = []
        collectedValues = {}
        expression = datasource.params.get('expression', None)
        debug = datasource.params.get('debug', None)

        if expression:
            # We will populate this with perf metrics and pass to eval().
            devdict = createDeviceDictionary(datasource.params['obj_attrs'])
            rrdValues = {}
            datapointDict = {}
            gotAllRRDValues = True

            for targetDatasource, targetDatapoint, targetRRA, targetAsRate, targets in datasource.params['targetDatapoints']:
                try:
                    value = yield rrdcache.getLastValue(
                        targetDatasource, targetDatapoint, targetRRA,
                        targetAsRate, datasource.cycletime*5, targets[0])
                except StandardError as ex:
                    description = dsDescription(datasource, devdict)
                    msg = "Failure before evaluation, %s" % description
                    severity = ZenEventClasses.Error if debug else ZenEventClasses.Debug
                    collectedEvents.append({
                        'eventKey': 'calculatedDataSourcePlugin_result',
                        'severity': severity,
                        'summary': msg})

                    logMethod = LOG.error if debug else LOG.debug
                    logMethod(msg + "\n%s", ex)
                    LOG.exception(ex)
                    continue

                # Datapoints can be specified in the following ways:
                #
                # 1. <dpname>
                # 2. <dsname>_<dpname>
                # 3. datapoint['<dpname>']
                # 4. datapoint['<dsname>_<dpname>']
                #
                # Option 1 and 3 can only be used in cases where the
                # referenced datapoint names are unique for the device
                # or component.
                #
                # Option 1 and 2 can only be used when the datapoint or
                # datasource_datapoint name are valid Python variable
                # names.
                #
                # Option 4 can only be used when there is not a
                # datapoint literally named "datapoint". This is most
                # likely the safest option if you can avoid naming your
                # datapoints "datapoint".

                if value is None:
                    gotAllRRDValues = False
                else:
                    fqdpn = '%s_%s' % (targetDatasource, targetDatapoint)

                    # Syntax 1
                    rrdValues[targetDatapoint] = value

                    # Syntax 2
                    rrdValues[fqdpn] = value

                    # Syntax 3
                    datapointDict[targetDatapoint] = value

                    # Syntax 4
                    datapointDict[fqdpn] = value

            result = None
            if gotAllRRDValues:
                devdict.update(rrdValues)
                devdict['datapoint'] = datapointDict

                description = dsDescription(datasource, devdict)

                try:
                    result = eval(expression, devdict)
                    if debug:
                        LOG.debug(
                            "Evaluation successful, result is %s for %s",
                            result, description)
                except ZeroDivisionError:
                    msg = (
                        "Evaluation failed due to attempted "
                        "division by zero, {descr}".format(
                            descr=description))

                    severity = ZenEventClasses.Error if debug else ZenEventClasses.Debug
                    collectedEvents.append({
                        'eventKey': 'calculatedDataSourcePlugin_result',
                        'severity': severity,
                        'summary': msg})

                    logMethod = LOG.warn if debug else LOG.debug
                    logMethod(msg)
                except (TypeError, Exception) as ex:
                    msg = "Evaluation failed due to {msg}, {descr}".format(
                        msg=ex.message, descr=description)
                    severity = ZenEventClasses.Error if debug else ZenEventClasses.Debug
                    collectedEvents.append({
                        'eventKey': 'calculatedDataSourcePlugin_result',
                        'severity': severity,
                        'summary': msg})

                    logMethod = LOG.exception if debug else LOG.debug
                    logMethod(msg + "\n%s", ex)
            else:
                logMethod = LOG.warn if debug else LOG.debug
                logMethod(
                    "Can't get RRD values for EXPR: %s --> DS: %s",
                    expression, get_ds_key(datasource))

            if result is not None:
                collectedValues.setdefault(datasource.component, {})
                collectedValues[datasource.component]['_'.join(
                    (datasource.datasource, datasource.points[0].id))] = (result, collectionTime)

        data = {
            'events': collectedEvents,
            'values': collectedValues,}

        returnValue(data)


DerivedProxyMap = {
    'AggregatingDataSource': AggregatingDataSourcePlugin(),
    'CalculatedPerformanceDataSource': CalculatedDataSourcePlugin()
}


class DerivedDataSourceProxyingPlugin(PythonDataSourcePlugin):

    # List of device attributes you'll need to do collection.
    proxy_attributes = tuple(chain(*map(
        lambda x: getattr(x, 'proxy_attributes', ()),
        DerivedProxyMap.values())))

    def __init__(self, config):
        self.log = ContextLogAdapter(
            LOG, {'context': '{} ({}):'.format(
                self.__class__.__name__, config.id)})
        # This is a per-run cache of latest RRD values by path+RRA,
        # used in case of multiple different aggregated datapoints
        # on a single target datasource.
        self.rrdcache = getReadThroughCache()

    @classmethod
    def config_key(cls, datasource, context):
        """
        Return a tuple defining collection uniqueness.

        This is a classmethod that is executed in zenhub. The datasource and
        context parameters are the full objects.

        This example implementation is the default. Split configurations by
        device, cycle time, template id, datasource id and the Python data
        source's plugin class name.

        You can omit this method from your implementation entirely if this
        default uniqueness behavior fits your needs. In many cases it will.

        """
        return (
            context.device().id,
            datasource.getCycleTime(context),
            datasource.plugin_classname)

    @classmethod
    def params(cls, datasource, context):
        """
        Return params dictionary needed for this plugin.

        This is a classmethod that is executed in zenhub. The datasource and
        context parameters are the full objects.

        If you only need extra
        information at the device level it is easier to just use
        proxy_attributes as mentioned above.

        """
        ds_plugin = DerivedProxyMap[datasource.__class__.__name__]
        proxy_params = ds_plugin.__class__.params(datasource, context)
        proxy_params['datasourceClassName'] = datasource.__class__.__name__
        return proxy_params

    @async_timeit(LOG, msg_prefix="Metric collection")
    @inlineCallbacks
    def _collect(self, config, datasources):
        self.log.debug("Collecting metrics")

        collectedEvents = []
        collectedValues = {}
        collectedMaps = []
        collected_ds_count = defaultdict(int)

        for ds in datasources:
            if 'datasourceClassName' not in ds.params or \
                    ds.params['datasourceClassName'] not in DerivedProxyMap:
                # Not our datasource, it's a dependency from elsewhere.
                continue

            collectionTime = time.time()

            ds_plugin = DerivedProxyMap[ds.params['datasourceClassName']]
            dsResult = yield ds_plugin.collect(
                config, ds, self.rrdcache, int(collectionTime))

            if dsResult:
                # Data for this collection won't be written until
                # the current task is entirely complete. To allow derivations
                # of derivations to complete in a single collection cycle,
                # we'll artificially cache the values here for every
                # possible RRA. These values may be slightly inaccurate,
                # as we're essentially always using the 'LAST' RRA.
                resultValues = dsResult.get('values', {}).get(
                    ds.component, {})

                if resultValues:
                    collectedPoints = (
                        p for p in ds.points
                        if p.id in resultValues or '_'.join(
                        (ds.datasource, p.id)) in resultValues)

                    for datapoint in collectedPoints:
                        rrdPath = datapoint.rrdPath.rsplit('/', 1)[0]

                        # Datapoint metadata only exists in Zenoss 5.
                        if hasattr(datapoint, 'metadata'):
                            contextUUID = datapoint.metadata["contextUUID"]
                        else:
                            contextUUID = rrdPath

                        value = (
                            resultValues.get(datapoint.id, None) or
                            resultValues.get('_'.join(
                                (ds.datasource, datapoint.id))))[0]

                        for rra in ('AVERAGE', 'MIN', 'MAX', 'LAST'):
                            self.rrdcache.put(
                                ds.datasource, datapoint.id, rra,
                                rrdPath, contextUUID, value)

                # Incorporate results returned from the proxied method.
                collectedEvents.extend(dsResult.get('events', []))
                collectedMaps.extend(dsResult.get('maps', []))
                collectedValues.setdefault(ds.component, {})
                collectedValues[ds.component].update(resultValues)
                ds_class_name = ds.params['datasourceClassName']
                collected_ds_count[ds_class_name] += 1

        self.log.debug("Collected datasources: %s", collected_ds_count)

        returnValue({
            'events': collectedEvents,
            'values': collectedValues,
            'maps': collectedMaps})

    @inlineCallbacks
    def collect(self, config):
        sorted_datasources = list(toposort(config.datasources))

        # If we are able prefetch all the metrics that we can.
        if hasattr(self.rrdcache, "batchFetchMetrics"):
            yield self.rrdcache.batchFetchMetrics(sorted_datasources)

        data = yield self._collect(config, sorted_datasources)

        self.log.debug("Returned data: %s", data)

        returnValue(data)

    def onComplete(self, result, config):
        """Called last for success and error."""
        self.log.debug(
            "Data collection completed, clearing out the cached metrics")
        self.rrdcache.invalidate()

        return result

    def cleanup(self, config):
        """Called when collector exits, or task is deleted or changed."""
        self.log.debug("Clearing out the threshold cache")
        for datasource in config.datasources:
            for datapoint in datasource.points:
                threshold_cache_key = getThresholdCacheKey(
                    datasource, datapoint)

                if threshold_cache_key in THRESHOLD_CACHE:
                    del THRESHOLD_CACHE[threshold_cache_key]
        return


@monkeypatch('Products.ZenModel.MinMaxThreshold.MinMaxThresholdInstance')
def processEvent(self, evt):
    """
    event_dict = dict(
        device=self.context().deviceName,        < !-------------
        summary=summary,
        eventKey=self.id,                        < !-------------
        eventClass=self.eventClass,
        component=self.context().componentName,  < !-------------
        min=self.minimum,                        < !-------------
        max=self.maximum,                        < !-------------
        current=current,                         < !-------------
        severity=severity,
        datapoint=datapoint)                     < !-------------

    """
    values_key = '{device}_{component}_{datapoint}'.format(
        device=evt['device'],
        component=evt['component'],
        datapoint=evt.get('datapoint', ''))

    last_values = THRESHOLD_CACHE.get(values_key, None)
    if last_values:
        violating_elements = []
        for uid, value in last_values.iteritems():
            if value < evt['min'] or value > evt['max']:
                violating_elements.append((uid, value))
        evt['violator'] = violating_elements

    return original(self, evt)
