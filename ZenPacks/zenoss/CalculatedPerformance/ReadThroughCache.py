##############################################################################
#
# Copyright (C) Zenoss, Inc. 2014-2018, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

from collections import defaultdict
from datetime import datetime, timedelta
import time
import base64
import json
import logging

from StringIO import StringIO
from cookielib import CookieJar
from twisted.internet import reactor
from twisted.internet.defer import DeferredLock, CancelledError
from twisted.internet.error import TimeoutError

try:
    from twisted.web.client import Agent, CookieAgent, FileBodyProducer, readBody, HTTPConnectionPool
    from twisted.web.http_headers import Headers
    from Products.ZenUtils.MetricServiceRequest import getPool
    from Products.ZenUtils.metrics import ensure_prefix
except ImportError:
    # Zenoss 4 won't have CookieAgent or FileBodyProducer.
    # This is OK because RRDReadThroughCache doesn't use them.
    pass

metaDataPrefix = False
try:
    from Products.ZenUtils.metrics import ensure_metadata_prefix
    metaDataPrefix = True
except ImportError:
    pass

from twisted.internet.defer import inlineCallbacks
from Products.ZenCollector.interfaces import IDataService
from Products.ZenUtils.GlobalConfig import getGlobalConfiguration
from Products.ZenUtils.Executor import TwistedExecutor
from ZenPacks.zenoss.CalculatedPerformance.utils import get_target_id
from zope.component import getUtility


LOG = logging.getLogger('zen.ReadThroughCache')


size = 20
responseTimeout = 300
cookieJar = CookieJar()
agent = None
executor = None
pool = None

# Global lock to acquire if cookie is stale.
jar_lock = DeferredLock()


def getAgent():
    global agent
    if agent is None:
        agent = CookieAgent(
            Agent(reactor, connectTimeout=30, pool=getPool()), cookieJar)
    return agent


def getPool():
    global pool
    if pool is None:
        pool = HTTPConnectionPool(reactor)
        pool.maxPersistentPerHost = size
    return pool


def getExecutor():
    global executor
    if not executor:
        executor = TwistedExecutor(size)
    return executor


def add_timeout(deferred, seconds):
    """Raise TimeoutError on deferred after seconds.
    Returns original deferred.

    """
    def handle_timeout():
        deferred.cancel()

    timeout_d = reactor.callLater(seconds, handle_timeout)

    def handle_result(result):
        if timeout_d.active():
            timeout_d.cancel()

        return result

    deferred.addBoth(handle_result)

    def handle_failure(failure):
        if failure.check(CancelledError):
            raise TimeoutError(
                string="timeout after %s seconds" % seconds)

        return failure

    deferred.addErrback(handle_failure)
    return deferred


class ReadThroughCache(object):

    def __init__(self):
        self._cache = {}

    def _getKey(self, datasource, datapoint, rra, targetValue):
        return '%s/%s_%s_%s' % (targetValue, datasource, datapoint, rra)

    def getLastValues(
            self, datasource, datapoint,
            rra='AVERAGE', rate=False, ago=300, targets=()):
        """
        Get the last value from the specified rrd for each target.

        @param datasource: target datasource id
        @param datapoint: target datapoint id
        @param rra: target RRA
        @param ago: how many seconds in the past to read, at maximum
        @param targets: iterable of dicts of target configurations, like:
            [{
                'device': {
                    'id': 'localhost',
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
                valueMap[targetConfig['uuid']] = self.getLastValue(
                    datasource, datapoint, rra, rate, ago, targetConfig)
            except StandardError as ex:
                msg = "Failure reading configured datapoint %s_%s on target %s" % \
                      (datasource, datapoint, get_target_id(targetConfig))
                errors.append((ex, msg))
        return {k: v for k, v in valueMap.items() if v is not None}, errors

    def getLastValue(
            self, datasource, datapoint,
            rra='AVERAGE', rate=False, ago=300, targetConfig={}):
        """
        @param datasource: target datasource id
        @param datapoint: target datapoint id
        @param rra: target RRA
        @param ago: how many seconds in the past to read, at maximum
        @param targetConfig: dict of target configuration, like:
            {
                'device': {
                    'id': 'localhost',
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
            LOG.warn(
                "No %s present for target %s",
                self._targetKey, get_target_id(targetConfig))

            return None

        cacheKey = self._getKey(datasource, datapoint, rra, targetValue)
        # Fetch from the cache if able.
        if cacheKey in self._cache:
            LOG.debug(
                "Using cached value for %s: %s",
                cacheKey, self._cache[cacheKey])

            return self._cache[cacheKey]

        LOG.debug("Not using cached value for %s", cacheKey)

        # Provides a readValue only with RRDReadThroughCache implementation,
        # which is used in 4.x systems.
        readValue = self._readLastValue(
            targetValue, datasource, datapoint, rra, rate, ago, targetConfig)
        if readValue is not None:
            self._cache[cacheKey] = readValue
            return readValue
        else:
            LOG.debug(
                "Last value for target %s not present for datapoint %s_%s",
                get_target_id(targetConfig), datasource, datapoint)

    def invalidate(self, key=None):
        if key is not None:
            if key in self._cache:
                del self._cache[key]
            return
        else:
            self._cache = {}

    def put(self, datasource, datapoint, rra, targetPath, targetID, value):
        """Place a value in the rrd cache."""
        val = targetPath
        if self._targetKey == "uuid":
            val = targetID
        cacheKey = self._getKey(datasource, datapoint, rra, val)
        self._cache[cacheKey] = value


class RRDReadThroughCache(ReadThroughCache):
    def __init__(self):
        from Products.ZenModel.PerformanceConf import performancePath

        super(RRDReadThroughCache, self).__init__()

        self._targetKey = 'rrdpath'
        self._performancePath = performancePath

    def _readLastValue(
            self, targetPath, datasource, datapoint,
            rra='AVERAGE', rate=False, ago=300, targetConfig={}):
        realPath = self._performancePath(targetPath) + '/%s_%s.rrd' % (
            datasource, datapoint)

        try:
            result = getUtility(IDataService).readRRD(
                str(realPath), rra, 'now-%ds' % ago, 'now')
        except StandardError:
            return None

        if result is not None:
            # Filter RRD's last 1-2 NaNs out of here,
            # use the latest available value.
            nonNans = filter(lambda x:
                             filter(lambda y:
                                    y is not None, x),
                             result[2])
            if nonNans:
                return nonNans[-1][0]


class BaseMetricServiceReadThroughCache(ReadThroughCache):
    # TODO: refactor this to use Products/ZenUtils/MetricServiceRequest.py

    def __init__(self):
        from Products.Zuul.facades.metricfacade import (
            DATE_FORMAT, AGGREGATION_MAPPING)
        from Products.Zuul.interfaces import IAuthorizationTool

        super(BaseMetricServiceReadThroughCache, self).__init__()

        self._datefmt = DATE_FORMAT
        self._aggMapping = AGGREGATION_MAPPING
        self._targetKey = 'uuid'

        creds = IAuthorizationTool(None).extractGlobalConfCredentials()
        auth = base64.b64encode('{login}:{password}'.format(**creds))
        self.agent = getAgent()
        self._headers2 = Headers({
            'Authorization': ['basic %s' % auth],
            'Content-Type': ['application/json'],
            'User-Agent': ['Zenoss: ZenPacks.zenoss.CalculatedPerformance']})

    def _readLastValue(
            self, uuid, datasource, datapoint,
            rra='AVERAGE', rate=False, ago=300, targetConfig={}):
        LOG.debug(
            "should not need to fetch metric: %s_%s",
            datasource, datapoint)

    @inlineCallbacks
    def batchFetchMetrics(self, datasources):
        LOG.debug("Batch Fetching metrics from central query")
        from Products.ZenUtils.metrics import ensure_prefix

        sourcetypes = defaultdict(int)
        dsPoints = set()

        for ds in datasources:
            for dp in ds.points:
                if metaDataPrefix:
                    dsdpID = ensure_prefix(dp.metadata, dp.dpName)
                else:
                    dsdpID = "{uuid}/{datapoint}".format(
                        uuid=dp.metadata["contextUUID"],
                        datapoint=dp.dpName)

                if dsdpID in dsPoints:
                    LOG.debug("Already found in ds points %s", dsdpID)
                else:
                    dsPoints.add(dsdpID)
        metrics = {}
        max_cycletime = 0
        for datasource in datasources:
            try:
                if datasource.cycletime > max_cycletime:
                    max_cycletime = datasource.cycletime
            except AttributeError:
                pass

            for dsname, datapoint, rra, rate, targets in datasource.params['targetDatapoints']:
                for targetConfig in targets:
                    targetValue = targetConfig.get(self._targetKey, None)
                    uuid = targetValue
                    # filter out target datapoints that match a datasource datapoint
                    # Target datapoints are what a datasource is made up of, if the
                    # target point is also a datasource datapoint that means we don't
                    # have to query for it since it will be calculated
                    #rrdpath in target config is json string of metricmetadata
                    metricMeta = json.loads(targetConfig.get('rrdpath', "{}"))
                    dpName = "%s_%s" % (dsname, datapoint)
                    if metaDataPrefix:
                        filterKey = ensure_prefix(metricMeta, dpName)
                    else:
                        filterKey = "{uuid}/{ds}_{dp}".format(
                            uuid=targetConfig.get("uuid", None),
                            ds=dsname,
                            dp=datapoint)

                    if filterKey in dsPoints:
                        LOG.debug(
                            "Skipping target datapoint %s, "
                            "since also a datasource datapoint",
                            filterKey)
                        continue

                    cachekey = self._getKey(dsname, datapoint, rra, targetValue)
                    if metaDataPrefix:
                        name = ensure_prefix(metricMeta, dpName)
                    else:
                        if not targetConfig.get('device'):
                            deviceId = targetConfig.get('id')
                        else:
                            deviceId = targetConfig['device']['id']
                        name = ensure_prefix(deviceId, dsname + "_" + datapoint)

                    dsclassname = datasource.params['datasourceClassName']
                    sourcetypes[dsclassname] += 1
                    self._insert_key(metrics, name, rra, rate, uuid, cachekey)

        if not len(metrics):
            return

        end, start = self._get_end_and_start(ago=(max_cycletime or 3600) * 5)
        chunkSize = 1000

        yield self.fetchChunks(
            chunkSize, end, start, metrics.values(), sourcetypes)

    @inlineCallbacks
    def fetchChunks(self, chunkSize, end, start, metrics, sourcetypes):
        LOG.debug(
            "About to request %s metrics from Central Query, in chunks of %s",
            len(metrics), chunkSize)

        # Check if all cookies in the jar are fresh.
        def _is_cookie_fresh():
            _is_cookie = False
            for _cookie in cookieJar:
                _is_cookie = True
                LOG.debug(
                    "Cookie:%s, name:%s, value:%s, port:%s, path:%s, expired:%s",
                    _cookie, _cookie.name, _cookie.value, _cookie.port,
                    _cookie.path, _cookie.is_expired())

                if _cookie.is_expired():
                    return False

            if _is_cookie:
                return True
            else:
                return False

        startPostTime = time.time()
        for x in range(0, len(metrics) / chunkSize + 1):
            ms = metrics[x * chunkSize:x * chunkSize + chunkSize]
            if not len(ms):
                LOG.debug("Skipping chunk at x %s", x)
                continue

            yield jar_lock.acquire()
            # If cookie is not fresh, we'll hold the lock
            # until cacheSome returns.
            if _is_cookie_fresh():
                jar_lock.release()
                _refreshing = False
            else:
                cookieJar.clear()
                _refreshing = True

            try:
                yield self.cacheSome(end, start, ms)
            except Exception as ex:
                msg = "Failure caching metrics: %s" % (ms)
                LOG.error((ex, msg))

            if _refreshing:
                jar_lock.release()

        endPostTime = time.time()
        timeTaken = endPostTime - startPostTime
        timeLogFn = LOG.debug
        if timeTaken > 60.0:
            timeLogFn = LOG.warn
        timeLogFn(
            "Took %.1f seconds total to batch fetch metrics in chunks of %s: %s",
            timeTaken, chunkSize, sourcetypes)

    def cacheSome(self, end, start, metrics):
        LOG.debug("Metrics: %s", metrics)
        request = dict(returnset=self._returnset, start=start, end=end)
        request[self._metrics_key] = metrics
        body = FileBodyProducer(StringIO(json.dumps(request)))
        def httpCall():
            return self.agent.request(
                'POST', self._metric_url, self._headers2, body)

        d = getExecutor().submit(httpCall)
        d.addCallbacks(self.handleMetricResponse, self.onError)

        return add_timeout(d, responseTimeout)

    def onError(self, reason):
        LOG.warn("Unable to fetch metrics from central query: %s", reason)
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
            name='%s' % cachekey)

        LOG.debug("Cache key: %s %s", cachekey, _tmp)
        metrics[cachekey] = _tmp

    def _get_end_and_start(self, ago):
        today = datetime.today()
        end = today.strftime(self._datefmt)
        start = (today - timedelta(seconds=ago)).strftime(self._datefmt)
        return end, start

    def onMetricsFetch(self, response):
        results = json.loads(response)['results']
        LOG.debug("Success retrieving %s results", len(results))
        for row in results:
            if row.get('datapoints'):
                value = row.get('datapoints')[0]['value']
                # row['metric'] is a combination of UUID,
                # datasource, datapoint and RRA. 
                self._cache[row['metric']] = value
                LOG.debug(
                    "Cached %s: %s", row['metric'],
                    self._cache[row['metric']])
            else:
                # Put an entry so we don't fetch it again.
                self._cache[row['metric']] = None
                LOG.debug("Unable to cache %s", row['metric'])

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
            metrics[name] = dict(
                metric=name,
                rate=rate,
                rateOptions=rateOptions_for_rate(rate),
                tags=dict(contextUUID=["*"]))

    def _get_end_and_start(self, ago):
        end = int(time.time())
        start = end - ago
        return end, start

    def onMetricsFetch(self, response):
        results = json.loads(response)['series']
        LOG.debug("Success retrieving %s results", len(results))
        for row in results:
            metricName = row["metric"].rsplit("/", 1)[-1]
            contextUUID = row["tags"]["contextUUID"]
            cacheKey = "%s/%s_AVERAGE" % (contextUUID, metricName)
            if row.get('datapoints'):
                value = row.get('datapoints')[0][1]
                self._cache[cacheKey] = value
            else:
                # Put an entry so we don't fetch it again.
                self._cache.setdefault(cacheKey, None)
                LOG.debug("unable to cache %s", cacheKey)

        return len(results)


def getReadThroughCache():
    try:
        import Products.Zuul.facades.metricfacade
        try:
            from Products.Zuul.facades.metricfacade import WILDCARD_URL_PATH
            LOG.debug(
                "CalculatedPerformance is using "
                "WildcardMetricServiceReadThroughCache")
            return WildcardMetricServiceReadThroughCache()

        except ImportError, e:
            # Must be 5.0.x.
            LOG.debug(
                "CalculatedPerformance is using "
                "MetricServiceReadThroughCache")
            return MetricServiceReadThroughCache()

    except ImportError, e:
        # Must be 4.x.
        LOG.debug("CalculatedPerformance is using RRDReadThroughCache")
        return RRDReadThroughCache()


def rateOptions_for_rate(rate):
    """Return a rateOptions dict given rate as a boolean."""
    return {'counter': True, 'resetThreshold': 1} if rate else {}
