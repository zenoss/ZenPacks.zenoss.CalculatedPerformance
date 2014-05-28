# 
# Copyright (C) Zenoss, Inc. 2014, all rights reserved.
# 
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
from itertools import chain, izip
import logging
import time
from twisted.internet.defer import inlineCallbacks, returnValue
from Products import Zuul

from Products.ZenEvents import ZenEventClasses
from Products.ZenModel.DeviceComponent import DeviceComponent
from Products.ZenUtils.Utils import monkeypatch
from Products.Zuul import IInfo
from ZenPacks.zenoss.CalculatedPerformance import operations
from ZenPacks.zenoss.CalculatedPerformance.RRDReadThroughCache import RRDReadThroughCache
from ZenPacks.zenoss.CalculatedPerformance.utils import toposort, getTargetId, grouper, dotTraverse, getVarNames, createDeviceDictionary
from ZenPacks.zenoss.PythonCollector.datasources.PythonDataSource \
    import PythonDataSourcePlugin
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

def dsKey(ds):
    return '%s_%s:%s' % (
        ds.device,
        ds.component or '',
        ds.datasource
    )

def dsTargetKeys(ds):
    """
    ds should have two params:
        targets: list of targetInfo dicts from targetInfo(target) below.
        targetDatapoints: list of tuples of (datasource_id, datapoint_id, RRA)
    """
    targetKeys = set()
    for target in ds.params.get('targets', []):
        targetElementId = getTargetId(target)
        for targetDatapoint in ds.params.get('targetDatapoints', []):
            targetKeys.add('%s:%s' % (targetElementId, targetDatapoint[0]))
    return targetKeys


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


class AggregatingDataSourcePlugin(object):

    @classmethod
    def params(cls, datasource, context):
        targetInfos = []
        # add an id->contents map for each component/device
        for member in dotTraverse(context, datasource.targetMethod or '') or []:
            targetInfos.append(targetInfo(member))

        targetArgValues = []
        for datapoint in datasource.datapoints():
            for att in getVarNames(datapoint.arguments.strip()):
                targetArgValues.append(dotTraverse(context, att))
            # should be only datapoint, so ...
            break

        return dict(
            targetDatapoints = [(datasource.targetDataSource, datasource.targetDataPoint,
                                 datasource.targetRRA or 'AVERAGE')],
            targetArgValues=[tuple(targetArgValues)],
            targets=targetInfos
        )

    @inlineCallbacks
    def collect(self, config, datasource, rrdcache, collectionTime):
        collectedEvents = []
        collectedValues = {}

        #Aggregate datasources only have one target datapoint config
        targetDatasource, targetDatapoint, targetRRA = datasource.params['targetDatapoints'][0]

        targetValues = yield self.getLastValues(rrdcache,
                                                targetDatasource,
                                                targetDatapoint,
                                                targetRRA,
                                                datasource.cycletime,
                                                datasource.params['targets'])

        if not targetValues:
            if datasource.params['targets']:
                msg = "No target values collected for datasource %s" % dsKey(datasource)
                collectedEvents.append({
                    'summary': msg,
                    'eventKey': 'aggregatingDataSourcePlugin_novalues',
                    'severity': ZenEventClasses.Info,
                })
                log.info(msg)
            return

        for datapoint in datasource.points:
            try:
                aggregate, adjustedTargetValues = yield self.performAggregation(
                    datapoint.operation,
                    handleArguments(datasource.params['targetArgValues'][0], datapoint.arguments),
                    targetValues)
                log.debug("Aggregate value %s calculated for datapoint %s_%s on %s:%s",
                          str(aggregate), datasource.datasource, datapoint.id,
                          datasource.device, datasource.component)
            except Exception as ex:
                msg = "Error calculating aggregation for %s_%s: %s" % (
                    targetDatasource,
                    targetDatapoint,
                    ex.message
                )
                collectedEvents.append({
                    'summary': msg,
                    'eventKey': 'aggregatingDataSourcePlugin_result',
                    'severity': ZenEventClasses.Error,
                })
                log.exception(msg + "\n%s", ex)
                continue

            #stash values for the threshold to put in event details
            threshold_cache[getThresholdCacheKey(datasource, datapoint)] = adjustedTargetValues

            collectedValues.setdefault(datasource.component, {})
            collectedValues[datasource.component]['_'.join((datasource.datasource, datapoint.id))] = \
                (aggregate, collectionTime)

        returnValue({
            'events': collectedEvents,
            'values': collectedValues,
        })

    @inlineCallbacks
    def getLastValues(self, rrdcache, datasource, datapoint, rra='AVERAGE', cycleTime=300, targets=()):
        values = {}
        for chunk in grouper(RRD_READ_CHUNKS, targets):
            chunkDict = yield rrdcache.getLastValues(datasource, datapoint, rra, cycleTime*5, chunk)
            values.update(chunkDict)
        returnValue(values)

    def performAggregation(self, operationId, arguments, targetValues):
        try:
            result, targetValues = getattr(operations, operationId)(targetValues, *arguments)
        except AttributeError as ex:
            raise Exception("Invalid aggregate operation specified: '%s'" % operationId, ex)

        return result, targetValues

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
        config = {
            'targets': [targetInfo(context)],
            'expression': datasource.expression
        }

        attrs = {}
        targetDataPoints = []

        allDatapointsByVarName = {}
        for dp in context.getRRDDataPoints():
            allDatapointsByVarName[dp.id] = dp
            allDatapointsByVarName[dp.name()] = dp

        for att in getVarNames(datasource.expression):

            if att in allDatapointsByVarName:
                datapoint = allDatapointsByVarName[att]
                targetDataPoints.append((datapoint.datasource().id, datapoint.id, 'AVERAGE'))
            else:
                value = dotTraverse(context, att)
                if not CalculatedDataSourcePlugin.isPicklable(value):
                    log.error("Calculated Performance expression %s references "
                        "invalid attribute (unpicklable value) %s" %(datasource.expression, att))
                    return config
                attrs[att] = value
                if value is None:
                    log.warn(
                        "Calculated Performance expression %s references "
                        "the variable %s which is not in %s" % (
                            datasource.expression, att, allDatapointsByVarName.keys()))

        config['obj_attrs'] = attrs
        config['targetDatapoints'] = targetDataPoints
        return config

    @inlineCallbacks
    def collect(self, config, datasource, rrdcache, collectionTime):
        collectedEvents = []
        collectedValues = {}
        expression = datasource.params.get('expression', None)
        if expression:
            # We will populate this with perf metrics and pass to eval()
            devdict = createDeviceDictionary(datasource.params['obj_attrs'])

            rrdValues = {}
            for targetDatasource, targetDatapoint, targetRRA in datasource.params['targetDatapoints']:
                value = yield rrdcache.getLastValue(targetDatasource,
                                                    targetDatapoint,
                                                    targetRRA,
                                                    datasource.cycletime*5,
                                                    datasource.params['targets'][0])
                # Datapoints can be referenced in the expression by datapoint id alone,
                # or by datasource_datapoint
                if value:
                    rrdValues[targetDatapoint] = value
                    rrdValues['%s_%s' % (targetDatasource, targetDatapoint)] = value

            result = None
            if len(rrdValues) == 2*len(datasource.params['targetDatapoints']):
                devdict.update(rrdValues)

                try:
                    result = eval(expression, devdict)
                    log.debug("Result of %s --> %s %s", expression, result, dsKey(datasource))
                except ZeroDivisionError:
                    msg = "Expression for %s (%s) failed: division by zero" % \
                          (dsKey(datasource), expression)
                    collectedEvents.append({
                        'summary': msg,
                        'eventKey': 'calculatedDataSourcePlugin_result',
                        'severity': ZenEventClasses.Error,
                    })
                    log.warn(msg)
                except (TypeError, Exception) as ex:
                    msg = "Expression for %s (%s) failed: %s" % \
                          (dsKey(datasource), expression, ex.message)
                    collectedEvents.append({
                        'summary': msg,
                        'eventKey': 'calculatedDataSourcePlugin_result',
                        'severity': ZenEventClasses.Error,
                        })
                    log.exception(msg + "\n%s", ex)
            else:
                log.debug("Can't get RRD values for EXPR: %s --> DS: %s" % (expression, dsKey(datasource)))

            if result is not None:
                collectedValues.setdefault(datasource.component, {})
                collectedValues[datasource.component]['_'.join((datasource.datasource, datasource.points[0].id))] = \
                    (result, collectionTime)

        returnValue({
            'events': collectedEvents,
            'values': collectedValues,
        })


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
        self.rrdcache = RRDReadThroughCache()

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

        datasourcesByKey = {dsKey(ds): ds for ds in config.datasources}
        datasourceDependencies = {dsKey(ds): dsTargetKeys(ds) for ds in config.datasources}

        for dskey in toposort(datasourceDependencies):
            datasource = datasourcesByKey.get(dskey, None)
            if datasource is None or \
               'datasourceClassName' not in datasource.params or \
               datasource.params['datasourceClassName'] not in DerivedProxyMap:
                #Not our datasource, it's a dependency from elsewhere
                continue

            collectionTime = time.time()

            dsResult = yield DerivedProxyMap[datasource.params['datasourceClassName']].collect(
                                                    config, datasource, self.rrdcache, collectionTime)

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
                        myPath = datapoint.rrdPath.rsplit('/', 1)[0]
                        value = (resultValues.get(datapoint.id, None) or
                                 resultValues.get('_'.join((datasource.datasource, datapoint.id))))[0]
                        for rra in ('AVERAGE', 'MIN', 'MAX', 'LAST'):
                            self.rrdcache.put(datasource.datasource, datapoint.id, rra, myPath, value)

                #incorporate results returned from the proxied method
                collectedEvents.extend(dsResult.get('events', []))
                collectedMaps.extend(dsResult.get('maps', []))
                collectedValues.setdefault(datasource.component, {})
                collectedValues[datasource.component].update(resultValues)

        returnValue({
            'events': collectedEvents,
            'values': collectedValues,
            'maps': collectedMaps
        })

    def onComplete(self, result, config):
        """Called last for success and error."""
        #Clear our cached RRD data
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
