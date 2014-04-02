# 
# Copyright (C) Zenoss, Inc. 2014, all rights reserved.
# 
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
import logging
from Products.ZenCollector.interfaces import IDataService
from Products.ZenModel.PerformanceConf import performancePath
from ZenPacks.zenoss.CalculatedPerformance.utils import getTargetId
from zope.component import getUtility

log = logging.getLogger('zen.RRDReadThroughCache')

class RRDReadThroughCache(object):
    def __init__(self):
        self._cache = {}

    def getKey(self, datasource, datapoint, rra, targetPath):
        return '%s/%s_%s_%s' % (targetPath, datasource, datapoint, rra)

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
        @return: a dictionary of {uuid -> last value} for each target element
        """
        valueMap = {
            targetConfig['uuid']: self.getLastValue(datasource, datapoint, rra, ago, targetConfig)
            for targetConfig in targets
        }
        return {k: v for k, v in valueMap.items() if v is not None}

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
        targetPath = targetConfig.get('rrdpath', None)
        if not targetPath:
            log.warn("No RRD path present for target %s", getTargetId(targetConfig))
            return None

        rrdcachekey = self.getKey(datasource, datapoint, rra, targetPath)
        #fetch from the cache if able
        if rrdcachekey in self._cache:
            log.debug("Using cached value for %s: %s", rrdcachekey, self._cache[rrdcachekey])
            return self._cache[rrdcachekey]

        readValue = None
        try:
            readValue = self._readLastValue(targetPath, datasource, datapoint, rra, ago)
        except StandardError as ex:
            log.debug("Failure reading RRD file for configured datapoint %s on target %s: %s",
                      '%s_%s' % (datasource, datapoint),
                      getTargetId(targetConfig),
                      ex)

        if readValue is not None:
            self._cache[rrdcachekey] = readValue
            return readValue
        else:
            log.debug("Last value for target %s not present for datapoint %s_%s",
                      getTargetId(targetConfig), datasource, datapoint)

    def _readLastValue(self, targetPath, datasource, datapoint, rra='AVERAGE', ago=300):
        realPath = performancePath(targetPath) + '/%s_%s.rrd' % (datasource, datapoint)
        result = getUtility(IDataService).readRRD(realPath, rra, 'now-%ds' % ago, 'now')

        if result is not None:
            # filter RRD's last 1-2 NaNs out of here, use the latest available value
            nonNans = filter(lambda x:
                             filter(lambda y:
                                    y is not None, x),
                             result[2])
            if nonNans:
                return nonNans[-1][0]

    def invalidate(self, key=None):
        if key is not None:
            if key in self._cache:
                del self._cache[key]
            return
        else:
            self._cache = {}

    def put(self, datasource, datapoint, rra, targetPath, value):
        """
        Place a value in the rrd cache
        """
        rrdcachekey = self.getKey(datasource, datapoint, rra, targetPath)
        self._cache[rrdcachekey] = value
