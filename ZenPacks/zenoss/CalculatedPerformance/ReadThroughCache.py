#
# Copyright (C) Zenoss, Inc. 2014, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
from datetime import datetime, timedelta
import base64
import json
import logging
from Products.ZenCollector.interfaces import IDataService
from Products.ZenUtils.GlobalConfig import getGlobalConfiguration
from ZenPacks.zenoss.CalculatedPerformance.utils import getTargetId
from zope.component import getUtility

log = logging.getLogger('zen.ReadThroughCache')

class ReadThroughCache(object):

    def _getKey(self, datasource, datapoint, rra, targetValue):
        return '%s/%s_%s_%s' % (targetValue, datasource, datapoint, rra)

    def getLastValues(self, datasource, datapoint, rra='AVERAGE', ago=300, targets=()):
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
                valueMap[targetConfig['uuid']] = self.getLastValue(datasource, datapoint, rra, ago, targetConfig)
            except StandardError as ex:
                msg = "Failure reading configured datapoint %s_%s on target %s" % \
                      (datasource, datapoint, getTargetId(targetConfig))
                errors.append((ex, msg))
        return {k: v for k, v in valueMap.items() if v is not None}, errors

    def getLastValue(self, datasource, datapoint, rra='AVERAGE', ago=300, targetConfig={}):
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
        readValue = self._readLastValue(targetValue, datasource, datapoint, rra, ago, targetConfig)

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

    def _readLastValue(self, targetPath, datasource, datapoint, rra='AVERAGE', ago=300, targetConfig={}):
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
    
    _requests = None

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
        self._headers = {
            'Authorization': 'basic %s' % auth,
            'content-type': 'application/json',
            'User-Agent': 'Zenoss: ZenPacks.zenoss.CalculatedPerformance'
        }

    def _readLastValue(self, uuid, datasource, datapoint, rra='AVERAGE', ago=300, targetConfig={}):
        from Products.ZenUtils.metrics import ensure_prefix
        metrics = []
        if targetConfig.get('device'):
            deviceId = targetConfig['device']['id']
        else:
            deviceId = targetConfig.get('id')
        if not deviceId:
            return None
        name = ensure_prefix(deviceId, datasource + "_" + datapoint)
        metrics.append(dict(
            metric=name,
            aggregator=self._aggMapping.get(rra.lower(), rra.lower()),
            rpn='',
            format='%.2lf',
            tags=dict(contextUUID=[uuid]),
            rate=False,
            name='%s_%s' % (uuid, datapoint)
        ))
        end = datetime.today().strftime(self._datefmt)
        start = (datetime.today() - timedelta(seconds=600)).strftime(self._datefmt)
        request = dict(
            returnset='LAST',
            start=start,
            end=end,
            metrics=metrics
        )
        response = self._requests.post(self._metric_url, json.dumps(request),
                headers=self._headers)
        if response.status_code > 199 and response.status_code < 300:
            results = response.json()['results']
            if results and results[0].get('datapoints'):
                return results[0]['datapoints'][-1]['value']

def getReadThroughCache():
    try:
        import Products.Zuul.facades.metricfacade
        if not MetricServiceReadThroughCache._requests:
            import requests
            MetricServiceReadThroughCache._requests = requests.Session()
        return MetricServiceReadThroughCache()
    except ImportError, e:
        # must be 4.x
        return RRDReadThroughCache()
