#
# Copyright (C) Zenoss, Inc. 2014-2017, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#

from collections import defaultdict
from itertools import chain, izip

import logging
import time
import traceback
from pprint import pformat
from twisted.internet.defer import inlineCallbacks, returnValue
from Products import Zuul

from Products.ZenEvents import ZenEventClasses
from Products.ZenModel.DeviceComponent import DeviceComponent
from Products.ZenUtils.Utils import monkeypatch
from Products.Zuul import IInfo
from ZenPacks.zenoss.CalculatedPerformance import (
    operations, USE_BASIS_INTERVAL, MINIMUM_INTERVAL, MAXIMUM_INTERVAL,)
from ZenPacks.zenoss.CalculatedPerformance.ReadThroughCache import getReadThroughCache
from ZenPacks.zenoss.CalculatedPerformance.utils import toposort, grouper, dotTraverse, getVarNames, createDeviceDictionary, dsKey
from ZenPacks.zenoss.PythonCollector.datasources.PythonDataSource \
    import PythonDataSourcePlugin
from ZenPacks.zenoss.CalculatedPerformance.AggregatingDataPoint import AggregatingDataPoint
import pickle

log = logging.getLogger('zen.CalculatingPlugin')

RRD_READ_CHUNKS = 20

# Map for lists of current values pre-aggregation, used to
# decorate threshold violation events
#
# key: 'deviceid_componentid_eventKey'
# value: map of target dev/component uuid + event key to
#        last values (or deviation values) used for aggregation
threshold_cache = {}
def getThresholdCacheKey(datasource, datapoint):
    return '%s_%s_%s_%s' % (datasource.device, datasource.component,
                            datasource.datasource, datapoint.id)


def getExtraTargets(extraContexts, device):
    """
    for each path in extraContexts, this retrieves only a device, or a component
    within a ToManyContRelationship on a device
    """
    targets = []

    for path in extraContexts:
        if path == 'device':
            targets.append(device)
            continue
        if path.count('/') != 1 :
            log.warn("path '%s' is not 'device' nor is it 2 tokens joined by "
                     "'/', skipping." % path)
            continue

        relname, extraId = path.split('/')
        rels = [r for r in device.objectValues(spec=('ToManyContRelationship',))
                if r.id == relname]

        if not rels:
            log.warn("the relname '%s' in path '%s' does not exist on device "
                     "%s, skipping." % (relname, path, device.id))
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
                log.warn("the contents of relationship %s on device %s is too "
                         "short to get member '%s', skipping'" % (relname,
                         device.id, extraId))
        else:
            log.warn("the component id '%s' in path '%s' does not exist on the "
                     "relationship %s on device %s, skipping." % (extraId, path,
                     relname, device.id))

    return targets


def dsDescription(ds, devdict):
    return """expression: %s
dictionary: %s
context device: %s
context component: %s
template: %s
datasource: %s
datapoint: %s""" % (
        ds.params.get('expression', None),
        pformat(devdict),
        ds.device,
        ds.component or '',
        ds.params.get('template', None),
        ds.datasource,
        ds.points[0].id
    )


def targetInfo(target):
    """
    Return a suitable target dictionary for Aggregate and Calculated target elements.
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
        arguments.append(targetArgValues[x] if getVarNames(tok) else tok.strip())
    return arguments


def getCollectionInterval(timestamps, minimumInterval, maximumInterval):
    """Determine the collection interval based on delta
    between the last and previous data collection.

    Args:
        timestamps (list): A list of two timestamps, 
            the first values is the previous collection timestamp and 
            the second values is the last collection timestamp.
        minimumInterval (int or None): The lowest possible value 
            for the interval.
        maximumInterval (int or None): The highest possible value 
            for the interval.

    Returns:
        int: A collection interval.

    """
    previousCollectionTime = timestamps[0]
    lastCollectionTime = timestamps[1]
    interval = lastCollectionTime - previousCollectionTime
    minimum = interval if minimumInterval is None else minimumInterval
    maximum = interval if maximumInterval is None else maximumInterval
    return max(1, max(min(maximum, interval), minimum))


def getCollectionIntervals(timestampCache, targetUuids,
                           targetDatasource, targetDatapoint, targetRRA,
                           minimumInterval, maximumInterval):
    """Determine the collection intervals for a particular datasource 
    based on its basis datapoints.

    Args:
        timestampCache (defaultdict): A cache with timestamps. 
        targetUuids (list): A list of component UUIDs to be processed.
        targetDatasource (str): Base datasource.
        targetDatapoint (str): Base datapoint.
        targetRRA (str): Round Robin Archive, AVERAGE by default.
        minimumInterval (int or None): The lowest possible value 
            for the interval.
        maximumInterval (int or None): The highest possible value 
            for the interval.

    Returns:
        list: The collection intervals.

    """
    intervals = []
    for targetUUID in targetUuids:
        cacheKey = "{0}/{1}_{2}_{3}".format(
            targetUUID, targetDatasource, targetDatapoint, targetRRA)
        timestamps = timestampCache.get(cacheKey)
        if timestamps and len(timestamps) > 1:
            interval = getCollectionInterval(
                timestamps, minimumInterval, maximumInterval)
            if interval:
                intervals.append(interval)
    return intervals


class AggregatingDataSourcePlugin(object):

    @classmethod
    def params(cls, datasource, context):
        targetInfos = []
        # add an id->contents map for each component/device
        for member in dotTraverse(context, datasource.targetMethod or '') or []:
            targetInfos.append(targetInfo(member))

        targetArgValues = []
        for datapoint in datasource.datapoints():
            if isinstance(datapoint, AggregatingDataPoint):
                for att in getVarNames(datapoint.arguments.strip()):
                    targetArgValues.append(dotTraverse(context, att))
            else:
                log.error("datasource %s has a datapoint of the wrong type %s" % (datasource, datapoint))

            # should be only datapoint, so ...
            break

        zDebug = context.getZ('zDatasourceDebugLogging')
        return dict(
            targetDatapoints = [(datasource.targetDataSource,
                                 datasource.targetDataPoint,
                                 datasource.targetRRA or 'AVERAGE',
                                 datasource.targetAsRate,
                                 targetInfos)],
            targetArgValues=[tuple(targetArgValues)],
            debug=datasource.debug or zDebug,
            useBasisInterval=datasource.useBasisInterval,
            minimumInterval=datasource.minimumInterval,
            maximumInterval=datasource.maximumInterval
        )

    @inlineCallbacks
    def collect(self, config, datasource, rrdcache, collectionTime):
        collectedEvents = []
        collectedValues = {}
        data = {}
        debug = datasource.params.get('debug', None)
        useBasisInterval = datasource.params.get(
            'useBasisInterval', USE_BASIS_INTERVAL)
        minimumInterval = datasource.params.get(
            'minimumInterval', MINIMUM_INTERVAL)
        maximumInterval = datasource.params.get(
            'maximumInterval', MAXIMUM_INTERVAL)

        #Aggregate datasources only have one target datapoint config
        targetDatasource, targetDatapoint, targetRRA, targetAsRate, targets = datasource.params['targetDatapoints'][0]

        targetValues, errors = yield self.getLastValues(rrdcache,
                                                targetDatasource,
                                                targetDatapoint,
                                                targetRRA,
                                                targetAsRate,
                                                datasource.cycletime,
                                                targets)

        logMethod = log.error if debug else log.debug
        for ex, msg in errors:
            logMethod('%s: %s', msg, ex)

        if not targetValues:
            if targets:
                msg = "No target values collected for datasource %s" % dsKey(datasource)
                collectedEvents.append({
                    'summary': msg,
                    'eventKey': 'aggregatingDataSourcePlugin_novalues',
                    'severity': ZenEventClasses.Info if debug else ZenEventClasses.Debug,
                })
                logMethod = log.info if debug else log.debug
                logMethod(msg)

            returnValue({
                'events': collectedEvents,
                'values': collectedValues,
            })

        if useBasisInterval:
            targetUuids = [t['uuid'] for t in targets if t['uuid']]
            collectionIntervals = getCollectionIntervals(
                rrdcache.timestampCache,
                targetUuids,
                targetDatasource,
                targetDatapoint,
                targetRRA,
                minimumInterval,
                maximumInterval)

            if collectionIntervals:
                data['interval'] = min(collectionIntervals)

        for datapoint in datasource.points:
            try:
                aggregate, adjustedTargetValues = yield self.performAggregation(
                    datapoint.operation,
                    handleArguments(datasource.params['targetArgValues'][0], datapoint.arguments),
                    targetValues)
            except AggregationError as e:
                prefix = "aggregation error for {}_{}".format(
                    targetDatasource,
                    targetDatapoint)

                collectedEvents.append({
                    'severity': ZenEventClasses.Error,
                    'summary': "{}: {}".format(prefix, e.summary),
                    'message': "{}: {}".format(prefix, e.message),
                    'eventClass': datasource.eventClass,
                    })

                continue

            if debug:
                log.debug(
                    "Aggregate value %s calculated for datapoint %s_%s on %s:%s",
                    str(aggregate), datasource.datasource, datapoint.id,
                    datasource.device, datasource.component)

            #stash values for the threshold to put in event details
            threshold_cache[getThresholdCacheKey(datasource, datapoint)] = adjustedTargetValues

            collectedValues.setdefault(datasource.component, {})
            collectedValues[datasource.component]['_'.join((datasource.datasource, datapoint.id))] = \
                (aggregate, collectionTime)

        data['events'] = collectedEvents
        data['values'] = collectedValues

        returnValue(data)

    @inlineCallbacks
    def getLastValues(self, rrdcache, datasource, datapoint, rra='AVERAGE', rate=False, cycleTime=300, targets=()):
        values = {}
        errors = []
        for chunk in grouper(RRD_READ_CHUNKS, targets):
            chunkDict, chunkErrors = yield rrdcache.getLastValues(datasource, datapoint, rra, rate, cycleTime*5, chunk)
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
            'template': datasource.rrdTemplate().getPrimaryId(),
            'useBasisInterval': datasource.useBasisInterval,
            'minimumInterval': datasource.minimumInterval,
            'maximumInterval': datasource.maximumInterval
        }

        attrs = {}
        targetDatapoints = {}

        # keep track of all datapoints from all targets so we can avoid
        # looking for an attribute when we have found a datapoint by name on
        # an earlier target already.
        combinedDatapoints = {}

        # extraContents can contain paths to other objects that could have
        # metrics or attributes.
        allTargets = getExtraTargets(datasource.extraContexts, context.device())
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
                    targetDatapoints[fqdpn] = (datapoint.datasource().id,
                                               datapoint.id,
                                               'AVERAGE',
                                               datasource.targetAsRate,
                                               [targetInfo(target)])

                elif att not in combinedDatapoints:
                    value = dotTraverse(target, att)
                    if not CalculatedDataSourcePlugin.isPicklable(value):
                        log.error("Calculated Performance expression %s references "
                                  "invalid attribute (unpicklable value) %s" % (
                                  datasource.expression, att))
                        return config

                    # only store None if we finished and never found
                    # a more interesting value
                    if value is not None:
                        attrs[att] = value
                    elif att not in attrs and not hasMore:
                        attrs[att] = value
                        log.warn("Calculated Performance expression %s references "
                                 "the variable %s which is not in %s on the targets %s" % (
                                 datasource.expression, att,
                                 combinedDatapoints.keys(), allTargets))

        config['obj_attrs'] = attrs
        config['targetDatapoints'] = targetDatapoints.values()
        return config

    @inlineCallbacks
    def collect(self, config, datasource, rrdcache, collectionTime):
        collectedEvents = []
        collectedValues = {}
        collectionIntervals = []
        expression = datasource.params.get('expression', None)
        debug = datasource.params.get('debug', None)
        useBasisInterval = datasource.params.get(
            'useBasisInterval', USE_BASIS_INTERVAL)
        minimumInterval = datasource.params.get(
            'minimumInterval', MINIMUM_INTERVAL)
        maximumInterval = datasource.params.get(
            'maximumInterval', MAXIMUM_INTERVAL)

        if expression:
            # We will populate this with perf metrics and pass to eval()
            devdict = createDeviceDictionary(datasource.params['obj_attrs'])
            rrdValues = {}
            datapointDict = {}
            gotAllRRDValues = True

            for targetDatasource, targetDatapoint, targetRRA, targetAsRate, targets in datasource.params['targetDatapoints']:
                try:
                    value = yield rrdcache.getLastValue(targetDatasource,
                                                        targetDatapoint,
                                                        targetRRA,
                                                        targetAsRate,
                                                        datasource.cycletime*5,
                                                        targets[0])

                except StandardError as ex:
                    description = dsDescription(datasource, devdict)
                    msg = "Failure before evaluation, %s" % description
                    collectedEvents.append({
                        'eventKey': 'calculatedDataSourcePlugin_result',
                        'severity': ZenEventClasses.Error if debug else ZenEventClasses.Debug,
                        'summary': msg,
                    })
                    logMethod = log.error if debug else log.debug
                    logMethod(msg + "\n%s", ex)
                    log.exception(ex)
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
                    if useBasisInterval:
                        targetUuids = [t['uuid'] for t in targets if t['uuid']]
                        collectionIntervals.extend(
                            getCollectionIntervals(
                                rrdcache.timestampCache,
                                targetUuids,
                                targetDatasource,
                                targetDatapoint,
                                targetRRA,
                                minimumInterval,
                                maximumInterval))

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
                        log.debug("Evaluation successful, result is %s for %s" % (result, description))
                except ZeroDivisionError:
                    msg = "Evaluation failed due to attempted division by zero, %s" % description
                    collectedEvents.append({
                        'eventKey': 'calculatedDataSourcePlugin_result',
                        'severity': ZenEventClasses.Error if debug else ZenEventClasses.Debug,
                        'summary': msg,
                    })
                    logMethod = log.warn if debug else log.debug
                    logMethod(msg)
                except (TypeError, Exception) as ex:
                    msg = "Evaluation failed due to %s, %s" % (ex.message, description)
                    collectedEvents.append({
                        'eventKey': 'calculatedDataSourcePlugin_result',
                        'severity': ZenEventClasses.Error if debug else ZenEventClasses.Debug,
                        'summary': msg,
                    })
                    logMethod = log.exception if debug else log.debug
                    logMethod(msg + "\n%s", ex)
            else:
                logMethod = log.warn if debug else log.debug
                logMethod("Can't get RRD values for EXPR: %s --> DS: %s" % (expression, dsKey(datasource)))

            if result is not None:
                collectedValues.setdefault(datasource.component, {})
                collectedValues[datasource.component]['_'.join((datasource.datasource, datasource.points[0].id))] = \
                    (result, collectionTime)

        data = {
            'events': collectedEvents,
            'values': collectedValues,}

        if collectionIntervals:
            data['interval'] = min(collectionIntervals)

        returnValue(data)


DerivedProxyMap = {
    'AggregatingDataSource': AggregatingDataSourcePlugin(),
    'CalculatedPerformanceDataSource': CalculatedDataSourcePlugin()
}


class DerivedDataSourceProxyingPlugin(PythonDataSourcePlugin):

    # List of device attributes you'll need to do collection.
    proxy_attributes = tuple(chain(*map(lambda x:getattr(x, 'proxy_attributes', ()),
                                        DerivedProxyMap.values())))

    def __init__(self):
        #This is a per-run cache of latest RRD values by path+RRA, used in case of multiple
        #different aggregated datapoints on a single target datasource.
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
            datasource.plugin_classname,
        )

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
        proxyParams = DerivedProxyMap[datasource.__class__.__name__].__class__.params(datasource, context)
        proxyParams['datasourceClassName'] = datasource.__class__.__name__
        return proxyParams

    @inlineCallbacks
    def collect(self, config):
        collectedEvents = []
        collectedValues = {}
        collectedMaps = []
        collectedIntervals = []

        datasourcesByKey = {dsKey(ds): ds for ds in config.datasources}
        # if we are able prefetch all the metrics that we can
        if hasattr(self.rrdcache, "batchFetchMetrics"):
            datasources = [datasourcesByKey.get(ds) for ds in toposort(config.datasources, datasourcesByKey) if datasourcesByKey.get(ds)]
            yield self.rrdcache.batchFetchMetrics(datasources)

        startCollectTime = time.time()
        sourcetypes = defaultdict(int)
        for dskey in toposort(config.datasources, datasourcesByKey):
            datasource = datasourcesByKey.get(dskey, None)
            if datasource is None or \
                    'datasourceClassName' not in datasource.params or \
                    datasource.params['datasourceClassName'] not in DerivedProxyMap:
                #Not our datasource, it's a dependency from elsewhere
                #log.warn("not using ds: %s %s %s", dskey, datasource, datasource.params.__dict__)
                continue

            collectionTime = time.time()

            dsResult = yield DerivedProxyMap[datasource.params['datasourceClassName']].collect(
                config, datasource, self.rrdcache, int(collectionTime))

            if dsResult:
                # Data for this collection won't be written until the current task
                # is entirely complete. To allow derivations of derivations to complete in
                # a single collection cycle, we'll artificially cache the values here for
                # every possible RRA. These values may be slightly inaccurate, as we're
                # essentially always using the 'LAST' RRA.
                resultValues = dsResult.get('values', {}).get(datasource.component, {})
                if resultValues:
                    collectedPoints = (p for p in datasource.points
                                       if p.id in resultValues or \
                                          '_'.join((datasource.datasource, p.id)) in resultValues)

                    for datapoint in collectedPoints:
                        rrdPath = datapoint.rrdPath.rsplit('/', 1)[0]

                        # Datapoint metadata only exists in Zenoss 5.
                        if hasattr(datapoint, 'metadata'):
                            contextUUID = datapoint.metadata["contextUUID"]
                        else:
                            contextUUID = rrdPath

                        value = (resultValues.get(datapoint.id, None) or
                                 resultValues.get('_'.join((datasource.datasource, datapoint.id))))[0]
                        for rra in ('AVERAGE', 'MIN', 'MAX', 'LAST'):
                            self.rrdcache.put(datasource.datasource, datapoint.id, rra, rrdPath, contextUUID, value)

                #incorporate results returned from the proxied method
                collectedEvents.extend(dsResult.get('events', []))
                collectedMaps.extend(dsResult.get('maps', []))
                collectedValues.setdefault(datasource.component, {})
                collectedValues[datasource.component].update(resultValues)
                dsclassname = datasource.params['datasourceClassName']
                sourcetypes[dsclassname] += 1

                interval = dsResult.get('interval')
                if interval:
                    collectedIntervals.append(interval)

        endCollectTime = time.time()
        timeTaken = endCollectTime - startCollectTime
        timeLogFn = log.debug
        if timeTaken > 60.0 :
            timeLogFn = log.warn
        timeLogFn("  Took %.1f seconds to collect datasources: %s", timeTaken, sourcetypes)

        data = {
            'events': collectedEvents,
            'values': collectedValues,
            'maps': collectedMaps,}

        if collectedIntervals:
            data['interval'] = min(collectedIntervals)

        returnValue(data)

    def onComplete(self, result, config):
        """Called last for success and error."""
        # Clear our cached RRD data.
        self.rrdcache.invalidate()

        return result

    def cleanup(self, config):
        """
        Called when collector exits, or task is deleted or changed.
        """
        for datasource in config.datasources:
            for datapoint in datasource.points:
                threshold_cache_key = getThresholdCacheKey(datasource, datapoint)
                if threshold_cache_key in threshold_cache:
                    del threshold_cache[threshold_cache_key]
        return


@monkeypatch('Products.ZenModel.MinMaxThreshold.MinMaxThresholdInstance')
def processEvent(self, evt):
    """
    event_dict = dict(device=self.context().deviceName,        < !-------------
                      summary=summary,
                      eventKey=self.id,                        < !-------------
                      eventClass=self.eventClass,
                      component=self.context().componentName,  < !-------------
                      min=self.minimum,                        < !-------------
                      max=self.maximum,                        < !-------------
                      current=current,                         < !-------------
                      severity=severity,
                      datapoint=datapoint)                     < !-------------

    @param evt:
    @return:
    """
    values_key = '%s_%s_%s' % (evt['device'], evt['component'], evt.get('datapoint', ''))
    last_values = threshold_cache.get(values_key, None)
    if last_values:
        violating_elements = []
        for uid, value in last_values.iteritems():
            if value < evt['min'] or value > evt['max']:
                violating_elements.append((uid, value))
        evt['violator'] = violating_elements

    return original(self, evt)
