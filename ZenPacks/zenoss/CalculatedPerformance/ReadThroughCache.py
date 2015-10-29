#
# Copyright (C) Zenoss, Inc. 2014, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
from datetime import datetime, timedelta
import time
import base64
import json
import logging

from StringIO import StringIO
from cookielib import CookieJar
from twisted.internet import reactor

try:
    from twisted.web.client import Agent, CookieAgent, FileBodyProducer, readBody
    from twisted.web.http_headers import Headers
except ImportError:
    # Zenoss 4 won't have CookieAgent or FileBodyProducer. This is OK
    # because RRDReadThroughCache doesn't use them.
    pass

from twisted.internet.defer import inlineCallbacks
from Products.ZenCollector.interfaces import IDataService
from Products.ZenUtils.GlobalConfig import getGlobalConfiguration
from ZenPacks.zenoss.CalculatedPerformance.utils import getTargetId
from zope.component import getUtility

log = logging.getLogger('zen.ReadThroughCache')


class ReadThroughCache(object):
    def _getKey(self, datasource, datapoint, rra, targetValue):
        return '%s/%s_%s_%s' % (targetValue, datasource, datapoint, rra)

    def getLastValues(self, datasource, datapoint, rra='AVERAGE', rrdtype="GAUGE", ago=300, targets=()):
        """
        Get the last value from the specified rrd for each target.

        @param datasource: target datasource id
        @param datapoint: target datapoint id
        @param rra: target RRA
        @param ago: how many seconds in the past to read, at maximum
        @param targets: iterable of dicts of target configurations, like:
                               [{'device': {'id': 'localhost',
                                            'name': 'localhost',
                                            'uid': '/zport/dmd/Devices/Server/Linux/devices/localhost',
                                            'uuid': '7e8228b7-a2d6-4dbe-8e35-8b475ad8822e'},
                                 'id': 'eth0',
                                 'name': 'eth0',
                                 'rrdpath': 'Devices/localhost/os/interfaces/eth0',
                                 'uid': '/zport/dmd/Devices/Server/Linux/devices/localhost/os/interfaces/eth0',
                                 'uuid': 'c35cdc58-a630-42be-b2d4-861c5c02362c'}]
        @return: 2 item tuple, containing:
            a dictionary of {uuid -> last value} for each target element,
            a list of tuples of exceptions, messages
        """
        valueMap = {}
        errors = []
        for targetConfig in targets:
            try:
                valueMap[targetConfig['uuid']] = self.getLastValue(datasource, datapoint, rra, rrdtype, ago,
                                                                   targetConfig)
            except StandardError as ex:
                msg = "Failure reading configured datapoint %s_%s on target %s" % \
                      (datasource, datapoint, getTargetId(targetConfig))
                errors.append((ex, msg))
        return {k: v for k, v in valueMap.items() if v is not None}, errors

    def getLastValue(self, datasource, datapoint, rra='AVERAGE', rrdtype="GAUGE", ago=300, targetConfig={}):
        """

        @param datasource: target datasource id
        @param datapoint: target datapoint id
        @param rra: target RRA
        @param ago: how many seconds in the past to read, at maximum
        @param targetConfig: dict of target configuration, like:
                             {'device': {'id': 'localhost',
                                         'name': 'localhost',
                                         'uid': '/zport/dmd/Devices/Server/Linux/devices/localhost',
                                         'uuid': '7e8228b7-a2d6-4dbe-8e35-8b475ad8822e'},
                              'id': 'eth0',
                              'name': 'eth0',
                              'rrdpath': 'Devices/localhost/os/interfaces/eth0',
                              'uid': '/zport/dmd/Devices/Server/Linux/devices/localhost/os/interfaces/eth0',
                              'uuid': 'c35cdc58-a630-42be-b2d4-861c5c02362c'}
        @return: last single value from the requested RRD file, or None if not available
        """
        targetValue = targetConfig.get(self._targetKey, None)
        if not targetValue:
            log.warn("No %s present for target %s" % (self._targetKey, getTargetId(targetConfig)))
            return None

        cachekey = self._getKey(datasource, datapoint, rra, targetValue)
        # fetch from the cache if able
        if cachekey in self._cache:
            log.debug("Using cached value for %s: %s", cachekey, self._cache[cachekey])
            return self._cache[cachekey]
        log.debug("Not Using cached value for %s", cachekey)
        readValue = self._readLastValue(targetValue, datasource, datapoint, rra, rrdtype, ago, targetConfig)

        if readValue is not None:
            self._cache[cachekey] = readValue
            return readValue
        else:
            log.debug("Last value for target %s not present for datapoint %s_%s",
                      getTargetId(targetConfig), datasource, datapoint)

    def invalidate(self, key=None):
        if key is not None:
            if key in self._cache:
                del self._cache[key]
            return
        else:
            self._cache = {}

    def put(self, datasource, datapoint, rra, targetPath, targetID, value):
        """
        Place a value in the rrd cache
        """
        val = targetPath
        if self._targetKey == "uuid":
            val = targetID
        rrdcachekey = self._getKey(datasource, datapoint, rra, val)
        self._cache[rrdcachekey] = value


class RRDReadThroughCache(ReadThroughCache):
    def __init__(self):
        self._cache = {}
        self._targetKey = 'rrdpath'
        from Products.ZenModel.PerformanceConf import performancePath

        self._performancePath = performancePath

    def _readLastValue(self, targetPath, datasource, datapoint, rra='AVERAGE', rrdtype="GAUGE", ago=300,
                       targetConfig={}):
        realPath = self._performancePath(targetPath) + '/%s_%s.rrd' % (datasource, datapoint)

        try:
            result = getUtility(IDataService).readRRD(
                str(realPath), rra, 'now-%ds' % ago, 'now')
        except StandardError:
            return None

        if result is not None:
            # filter RRD's last 1-2 NaNs out of here, use the latest available value
            nonNans = filter(lambda x:
                             filter(lambda y:
                                    y is not None, x),
                             result[2])
            if nonNans:
                return nonNans[-1][0]


class BaseMetricServiceReadThroughCache(ReadThroughCache):
    # TODO: refactor this to use Products/ZenUtils/MetricServiceRequest.py

    # use a shared cookie jar so all Metric requests can share the same session
    cookieJar = CookieJar()

    def __init__(self):
        from Products.Zuul.facades.metricfacade import DATE_FORMAT, AGGREGATION_MAPPING

        self._datefmt = DATE_FORMAT
        self._aggMapping = AGGREGATION_MAPPING
        self._cache = {}
        self._targetKey = 'uuid'
        from Products.Zuul.interfaces import IAuthorizationTool

        creds = IAuthorizationTool(None).extractGlobalConfCredentials()
        auth = base64.b64encode('{login}:{password}'.format(**creds))
        self.agent = CookieAgent(Agent(reactor, connectTimeout=30), self.cookieJar)
        self._headers2 = Headers({
            'Authorization': ['basic %s' % auth],
            'Content-Type': ['application/json'],
            'User-Agent': ['Zenoss: ZenPacks.zenoss.CalculatedPerformance'],
        })

    def _readLastValue(self, uuid, datasource, datapoint, rra='AVERAGE', rrdtype="GAUGE", ago=300, targetConfig={}):
        from Products.ZenUtils.metrics import ensure_prefix

        metrics = []
        if targetConfig.get('device'):
            deviceId = targetConfig['device']['id']
        else:
            deviceId = targetConfig.get('id')
        if not deviceId:
            return None
        name = ensure_prefix(deviceId, datasource + "_" + datapoint)
        log.debug("should not need to fetch metric: %s %s_%s", name, uuid, datapoint)

    @inlineCallbacks
    def batchFetchMetrics(self, datasources):
        log.debug("Batch Fetching metrics from central query")
        from Products.ZenUtils.metrics import ensure_prefix
        from collections import defaultdict

        sourcetypes = defaultdict(int)

        dsPoints = set()

        for ds in datasources:
            for dp in ds.points:
                dsdpID = "%s/%s" % (dp.metadata["contextUUID"], dp.dpName)
                if dsdpID in dsPoints:
                    log.debug("already found in ds points %s", dsdpID)
                else:
                    dsPoints.add(dsdpID)
        metrics = {}
        for datasource in datasources:
            for dsname, datapoint, rra, rrdtype in datasource.params['targetDatapoints']:
                for targetConfig in datasource.params['targets']:
                    targetValue = targetConfig.get(self._targetKey, None)
                    uuid = targetValue
                    # filter out target datapoints that match a datasource datapoint
                    # Target datapoints are what a datasource is made up of, if the
                    # target point is also a datasource datapoint that means we don't
                    # have to query for it since it will be calculated
                    filterKey = "%s/%s_%s" % (targetConfig.get("uuid", None), dsname, datapoint)
                    if filterKey in dsPoints:
                        log.debug("skipping target datapoint %s, since also a datasource datapoint", filterKey)
                        continue
                    cachekey = self._getKey(dsname, datapoint, rra, targetValue)
                    if not targetConfig.get('device'):
                        deviceId = targetConfig.get('id')
                    else:
                        deviceId = targetConfig['device']['id']
                    name = ensure_prefix(deviceId, dsname + "_" + datapoint)
                    rate = rrdtype.lower() in ('counter', 'derive')
                    dsclassname = datasource.params['datasourceClassName']
                    sourcetypes[dsclassname] += 1
                    self._insert_key(metrics, name, rra, rate, uuid, cachekey)
        if not len(metrics):
            return

        end, start = self._get_end_and_start()
        chunkSize = 1000
        yield self.fetchChunks(chunkSize, end, start, metrics.values(), sourcetypes)

    @inlineCallbacks
    def fetchChunks(self, chunkSize, end, start, metrics, sourcetypes):
        log.debug("About to request %s metrics from Central Query, in chunks of %s", len(metrics), chunkSize)
        startPostTime = time.time()
        for x in range(0, len(metrics) / chunkSize + 1):
            ms = metrics[x * chunkSize:x * chunkSize + chunkSize]
            if not len(ms):
                log.debug("skipping chunk at x %s", x)
                continue
            try:
                yield self.cacheSome(end, start, ms)
            except Exception as ex:
                msg = "Failure caching metrics: %s" % (ms)
                log.error((ex, msg))

        endPostTime = time.time()
        timeTaken = endPostTime - startPostTime
        timeLogFn = log.debug
        if timeTaken > 60.0:
            timeLogFn = log.warn
        timeLogFn("  Took %.1f seconds total to batch fetch metrics in chunks of %s: %s", timeTaken, chunkSize,
                  sourcetypes)

    def cacheSome(self, end, start, metrics):
        log.debug("metrics: %s", metrics)
        request = dict(
            returnset=self._returnset,
            start=start,
            end=end
        )
        request[self._metrics_key] = metrics
        body = FileBodyProducer(StringIO(json.dumps(request)))
        d = self.agent.request('POST', self._metric_url, self._headers2, body)
        d.addCallbacks(self.handleMetricResponse, self.onError)
        return d

    def onError(self, reason):
        log.warn("Unable to fetch metrics from central query: %s", reason)
        return reason

    def handleMetricResponse(self, response):
        d = readBody(response)
        if response.code > 199 and response.code < 300:
            d.addCallback(self.onMetricsFetch)
        else:
            d.addCallback(self.onError)
        return d


class MetricServiceReadThroughCache(BaseMetricServiceReadThroughCache):

    def __init__(self):
        super(MetricServiceReadThroughCache, self).__init__()
        from Products.Zuul.facades.metricfacade import METRIC_URL_PATH
        urlstart = getGlobalConfiguration().get('metric-url', 'http://localhost:8080')
        self._metric_url = '%s/%s' % (urlstart, METRIC_URL_PATH)
        self._returnset = 'LAST'
        self._metrics_key = 'metrics'

    def _insert_key(self, metrics, name, rra, rate, uuid, cachekey):
        _tmp = dict(
            metric=name,
            aggregator=self._aggMapping.get(rra.lower(), rra.lower()),
            rpn='',
            rate=rate,
            rateOptions=rateOptions_for_rate(rate),
            format='%.2lf',
            tags=dict(contextUUID=[uuid]),
            name='%s' % cachekey
        )
        log.debug("cachekey: %s %s", cachekey, _tmp)
        metrics[cachekey] = _tmp

    def _get_end_and_start(self):
        today = datetime.today()
        end = today.strftime(self._datefmt)
        start = (today - timedelta(seconds=600)).strftime(self._datefmt)
        return end, start

    def onMetricsFetch(self, response):
        results = json.loads(response)['results']
        log.debug("Success retrieving %s results", len(results))
        for row in results:
            if row.get('datapoints'):
                self._cache[row['metric']] = row.get('datapoints')[0]['value']
                log.debug("cached %s: %s", row['metric'], self._cache[row['metric']])
            else:
                # put an entry so we don't fetch it again
                self._cache[row['metric']] = None
                log.debug("unable to cache %s", row['metric'])
        return len(results)


class WildcardMetricServiceReadThroughCache(BaseMetricServiceReadThroughCache):

    def __init__(self):
        super(WildcardMetricServiceReadThroughCache, self).__init__()
        from Products.Zuul.facades.metricfacade import WILDCARD_URL_PATH
        urlstart = getGlobalConfiguration().get('metric-url', 'http://localhost:8080')
        self._metric_url = '%s/%s' % (urlstart, WILDCARD_URL_PATH)
        self._returnset = 'last'
        self._metrics_key = 'queries'

    def _insert_key(self, metrics, name, rra, rate, uuid, cachekey):
        if name not in metrics:
            metrics[name]= dict(
                    metric=name,
                    rate=rate,
                    rateOptions=rateOptions_for_rate(rate),
                    tags=dict(contextUUID=["*"])
            )

    def _get_end_and_start(self):
        end = int(time.time())
        start = end - 600
        return end, start

    def onMetricsFetch(self, response):
        results = json.loads(response)['series']
        log.debug("Success retrieving %s results", len(results))
        for row in results:
            metricName = row["metric"]
            contextUUID = row["tags"]["contextUUID"]
            device = row["tags"]["device"]
            cacheKey = "%s/%s_AVERAGE" % (contextUUID, metricName.replace("%s/"%device, ""))
            if row.get('datapoints'):
                self._cache[cacheKey] = row.get('datapoints')[0][1]
            else:
                # put an entry so we don't fetch it again
                self._cache[cacheKey] = None
                log.debug("unable to cache %s", cacheKey)
        return len(results)


def getReadThroughCache():
    try:
        import Products.Zuul.facades.metricfacade
        try:
            from Products.Zuul.facades.metricfacade import WILDCARD_URL_PATH
            log.debug("CalculatedPerformance is using WildcardMetricServiceReadThroughCache")
            return WildcardMetricServiceReadThroughCache()

        except ImportError, e:
            # must be 5.0.x
            log.debug("CalculatedPerformance is using MetricServiceReadThroughCache")
            return MetricServiceReadThroughCache()

    except ImportError, e:
        # must be 4.x
        log.debug("CalculatedPerformance is using RRDReadThroughCache")
        return RRDReadThroughCache()


def rateOptions_for_rate(rate):
    """Return a rateOptions dict given rate as a boolean."""
    if rate:
        return {'counter': True, 'resetThreshold': 1}
    else:
        return {}
