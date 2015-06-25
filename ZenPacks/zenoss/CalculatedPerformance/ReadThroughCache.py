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
from twisted.web.client import Agent, CookieAgent, FileBodyProducer, readBody
from twisted.web.http_headers import Headers

from twisted.web.client import getPage
from twisted.internet.defer import inlineCallbacks, returnValue
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
                valueMap[targetConfig['uuid']] = self.getLastValue(datasource, datapoint, rra, rrdtype, ago, targetConfig)
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
        #fetch from the cache if able
        if cachekey in self._cache:
            log.debug("Using cached value for %s: %s", cachekey, self._cache[cachekey])
            return self._cache[cachekey]
        log.warn("Not Using cached value for %s", cachekey)
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

    def put(self, datasource, datapoint, rra, targetValue, value):
        """
        Place a value in the rrd cache
        """
        rrdcachekey = self._getKey(datasource, datapoint, rra, targetValue)
        self._cache[rrdcachekey] = value

class RRDReadThroughCache(ReadThroughCache):
    def __init__(self):
        self._cache = {}
        self._targetKey = 'rrdpath'
        from Products.ZenModel.PerformanceConf import performancePath
        self._performancePath = performancePath

    def _readLastValue(self, targetPath, datasource, datapoint, rra='AVERAGE', rrdtype="GAUGE", ago=300, targetConfig={}):
        realPath = self._performancePath(targetPath) + '/%s_%s.rrd' % (datasource, datapoint)
        result = getUtility(IDataService).readRRD(realPath, rra, 'now-%ds' % ago, 'now')

        if result is not None:
            # filter RRD's last 1-2 NaNs out of here, use the latest available value
            nonNans = filter(lambda x:
                             filter(lambda y:
                                    y is not None, x),
                             result[2])
            if nonNans:
                return nonNans[-1][0]

class MetricServiceReadThroughCache(ReadThroughCache):

    # TODO: refactor this to use Products/ZenUtils/MetricServiceRequest.py

    # use a shared cookie jar so all Metric requests can share the same session
    cookieJar = CookieJar()

    def __init__(self):
        from Products.Zuul.facades.metricfacade import DATE_FORMAT, METRIC_URL_PATH, AGGREGATION_MAPPING
        self._datefmt = DATE_FORMAT
        self._aggMapping = AGGREGATION_MAPPING
        self._cache = {}
        self._targetKey = 'uuid'
        urlstart = getGlobalConfiguration().get('metric-url', 'http://localhost:8080')
        self._metric_url = '%s/%s' % (urlstart, METRIC_URL_PATH)
        from Products.Zuul.interfaces import IAuthorizationTool
        creds = IAuthorizationTool(None).extractGlobalConfCredentials()
        auth = base64.b64encode('{login}:{password}'.format(**creds))
        self.agent = CookieAgent(Agent(reactor, connectTimeout=30), self.cookieJar)
        self._headers2 = Headers({
            'Authorization': ['basic %s' % auth],
            'content-type': ['application/json'],
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
        log.warn("should not need to fetch metric: %s %s_%s", name, uuid, datapoint)

    @inlineCallbacks
    def batchFetchMetrics(self, datasources):
        log.debug("Batch Fetching metrics from central query")
        from Products.ZenUtils.metrics import ensure_prefix
        from collections import defaultdict
        sourcetypes = defaultdict(int)
        metrics = {}
        for datasource in datasources:
            for dsname, datapoint, rra, rrdtype in datasource.params['targetDatapoints']:
                for targetConfig in datasource.params['targets']:
                    targetValue = targetConfig.get(self._targetKey, None)
                    uuid = targetValue
                    cachekey = self._getKey(dsname, datapoint, rra, targetValue)
                    if not targetConfig.get('device'):
                        deviceId = targetConfig.get('id')
                    else:
                        deviceId = targetConfig['device']['id']
                    name = ensure_prefix(deviceId, dsname + "_" + datapoint)
                    rate = rrdtype.lower() in ('counter', 'derive')
                    dsclassname = datasource.params['datasourceClassName']
                    sourcetypes[dsclassname] += 1
                    _tmp = dict(
                        metric=name,
                        aggregator=self._aggMapping.get(rra.lower(), rra.lower()),
                        rpn='',
                        rate=rate,
                        format='%.2lf',
                        tags=dict(contextUUID=[uuid]),
                        name='%s' % cachekey
                    )
                    metrics[cachekey] = _tmp
        if not len(metrics):
            return
        end = datetime.today().strftime(self._datefmt)
        start = (datetime.today() - timedelta(seconds=600)).strftime(self._datefmt)
        chunkSize = 100
        yield self.fetchChunks(chunkSize, end, start, metrics.values(), sourcetypes)

    @inlineCallbacks
    def fetchChunks(self, chunkSize, end, start, metrics, sourcetypes):
        log.debug("About to request %s metrics from Central Query, in chunks of %s", len(metrics), chunkSize)
        startPostTime = time.time()
        for x in range(0, len(metrics)/chunkSize + 1):
            yield self.cacheSome(end, start, metrics[x*chunkSize:x*chunkSize+chunkSize])
        endPostTime = time.time()
        timeTaken = endPostTime - startPostTime
        timeLogFn = log.debug
        if timeTaken > 60.0 :
            timeLogFn = log.warn
        timeLogFn("  Took %.1f seconds total to batch fetch metrics in chunks of %s: %s", timeTaken, chunkSize, sourcetypes)

    def cacheSome(self, end, start, metrics):
        request = dict(
            returnset='LAST',
            start=start,
            end=end,
            metrics=metrics
        )
        body = FileBodyProducer(StringIO(json.dumps(request)))
        d = self.agent.request('POST', self._metric_url, self._headers2, body)
        d.addCallbacks(self.handleMetricResponse, self.onError)
        return d

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

def getReadThroughCache():
    try:
        import Products.Zuul.facades.metricfacade
        return MetricServiceReadThroughCache()
    except ImportError, e:
        # must be 4.x
        return RRDReadThroughCache()
