######################################################################
#
# Copyright 2011 Zenoss, Inc.  All Rights Reserved.
#
######################################################################

import logging
import sys
import re
from time import ctime, time

from twisted.python.failure import Failure
from twisted.internet import defer, error

from pynetsnmp.twistedsnmp import snmpprotocol

import Globals
from zope.interface import implements
import zope.component

from Products.ZenCollector.daemon import CollectorDaemon
from Products.ZenCollector.interfaces import ICollectorPreferences,\
                                             IEventService,\
                                             IScheduledTask,\
                                             ICollector
from Products.ZenCollector.tasks import SimpleTaskFactory,\
                                        SimpleTaskSplitter,\
                                        TaskStates

from Products.ZenHub.services.PerformanceConfig import SnmpConnInfo
from Products.ZenUtils.observable import ObservableMixin
from Products.ZenUtils.Utils import unused

from Products.ZenCollector.services.config import DeviceProxy
unused(DeviceProxy)


COLLECTOR_NAME = "zencalcperfd"

log = logging.getLogger("zen.%s" % COLLECTOR_NAME)


class CalculatedPerformancePreferences(object):
    implements(ICollectorPreferences)

    def __init__(self):
        self.collectorName = COLLECTOR_NAME
        self.defaultRRDCreateCommand = None
        self.configCycleInterval = 60 # minutes
        self.cycleInterval = 60 # 1 minute

        self.configurationService = 'ZenPacks.zenoss.CalculatedPerformance.services.CalcPerfConfig'

        # No more than maxTasks models will take place at once
        self.maxTasks = 50

        self.options = None

    def buildOptions(self, parser):
        pass

    def postStartup(self):
        pass


# TODO: When switching to Avalon, use BaseTask
class CalculatedPerformanceCollectionTask(ObservableMixin):
    implements(IScheduledTask)

    STATE_CONNECTING = 'CONNECTING'
    STATE_FETCH_MODEL = 'FETCH_MODEL_DATA'
    STATE_PROCESS_MODEL = 'FETCH_PROCESS_MODEL_DATA'
    STATE_APPLY_DATAMAPS = 'FETCH_APPLY_MODEL_DATA'

    def __init__(self, deviceId, taskName, scheduledIntervalSeconds, taskConfig):
        super(CalculatedPerformanceCollectionTask, self).__init__()
        #super(CalculatedPerformanceCollectionTask, self).__init__(
        #    deviceId,
        #    taskName,
        #    scheduledIntervalSeconds,
        #    taskConfig)
        self.name = taskName
        self.configId = deviceId
        self.state = TaskStates.STATE_IDLE
        self.interval = scheduledIntervalSeconds
        
        self._device = taskConfig
        self._devId = deviceId
        self._manageIp = self._device.manageIp

        self._dataService = zope.component.queryUtility(IDataService)
        self._eventService = zope.component.queryUtility(IEventService)
        self._preferences = zope.component.queryUtility(ICollectorPreferences, COLLECTOR_NAME)

        self._collector = zope.component.queryUtility(ICollector)
        self._lastErrorMsg = ''

    def doTask(self):
        return defer.succeed("Yay!")

    def fetchRrdData(self, dps):
        for dataPointName, perfConfigs in dataPointConfigs.items():
            for perfConfig in perfConfigs:
                try:
                    output = {}
                    filePath = perfDir + '/Devices/' + perfConfig['filePath']
                    output['filePath'] = filePath
                    output['result'] = _fetch(
                        filePath,
                        'AVERAGE', # TODO: this won't be right for everything...
                        timeRange
                    )
                    output['cf'] = 'LAST' # TODO: this won't be right for everything...
                    output['values'] = values = {}
                    output['dataPointName'] = perfConfig['dataPointName']
                    yield output
                except errors.MissingRrdFileError, err:
                    LOG.warn('Missing RRD file: %s', err)
                    continue
                except (StandardError, rrdtool.error), err:
                    if STOP_ON_ERROR:
                        raise err
                    else:
                        LOG.error('Extract failed for %s (%s: %s)', 
                                  perfConfig['dataPointName'],
                                  err.__class__.__name__, 
                                  err)
                        LOG.debug(traceback.format_exc())
                        continue
    
    def _fetch(filePath, consolidationFunction, timeRange):
        """generate args for rrdtool.fetch based on the fetchSpec"""
        if not os.path.isfile(filePath):
            raise errors.MissingRrdFileError(filePath)
        start = '-s %s' % timeutils.toUnixTime(timeRange[0])
        end = '-e %s' % timeutils.toUnixTime(timeRange[1])
        return rrdtool.fetch(filePath, str(consolidationFunction), start, end)

    def cleanup(self):
        pass

    def displayStatistics(self):
        """
        Called by the collector framework scheduler, and allows us to
        see how each task is doing.
        """
        display = ''
        if self._lastErrorMsg:
            display += "%s\n" % self._lastErrorMsg
        return display


if __name__ == '__main__':
    myPreferences = CalculatedPerformancePreferences()
    myTaskFactory = SimpleTaskFactory(CalculatedPerformanceCollectionTask)
    myTaskSplitter = SimpleTaskSplitter(myTaskFactory)
    daemon = CollectorDaemon(myPreferences, myTaskSplitter)
    daemon.run()

