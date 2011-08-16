######################################################################
#
# Copyright 2011 Zenoss, Inc.  All Rights Reserved.
#
######################################################################

import logging
import sys
import re
import os.path
from time import ctime, time

import rrdtool

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
                                             ICollector, \
                                             IDataService
from Products.ZenCollector.tasks import SimpleTaskFactory,\
                                        SimpleTaskSplitter,\
                                        TaskStates

from Products.ZenHub.services.PerformanceConfig import SnmpConnInfo
from Products.ZenUtils.observable import ObservableMixin
from Products.ZenUtils.Utils import unused, zenPath

from Products.ZenCollector.services.config import DeviceProxy
unused(DeviceProxy)

from ZenPacks.zenoss.CalculatedPerformance.services.CalcPerfConfig import getVarNames

COLLECTOR_NAME = "zencalcperfd"

log = logging.getLogger("zen.%s" % COLLECTOR_NAME)

class MissingRrdFileError(StandardError):
    """RRD file is missing from the filesystem."""

class SimpleObject(object):
    """
    Simple class that can have arbitrary attributes assigned to it.
    """

def createDeviceDictionary(deviceProxy):
    """
    Returns a dictionary of simple objects suitable for passing into eval().
    """

    vars = {}

    for dp in deviceProxy.datapoints:
        for key, value in dp['obj_attrs'].items():
            # For example, turn here.hw.totalMemory=1024 into:
            # vars['here'].hw.totalMemory = 1024
            # This way, vars can be passed in to eval
            parts = key.split(".")
            base = vars[parts[0]] = SimpleObject()
            for part in parts[1:-1]:
                if not hasattr(base, part):
                    setattr(base, part, SimpleObject())
                base = getattr(base, part)
            setattr(base, parts[-1], value)

    return vars

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
        rrdStart = 'now-600s'
        rrdEnd = 'now'
        perfDir = zenPath('perf')

        for datapoint in self._device.datapoints:
            expression = datapoint['expression']
            obj_attrs = datapoint['obj_attrs']
            # We will populate this with perf metrics and pass to eval()
            vars = createDeviceDictionary(self._device)

            rrd_paths = datapoint['rrd_paths']
            varNames = getVarNames(expression)

            # If a variable is in the expression, but not the dict of object
            #   attributes, assume it is an RRD variable.
            rrdNames = [varName for varName in varNames
                if varName not in obj_attrs.keys()]

            log.debug("Perf to get: %s", rrdNames)
            for rrdName in rrdNames:
                filePath = os.path.join(perfDir, rrd_paths[rrdName])
                values = rrdtool.fetch(filePath,
                                       'AVERAGE',
                                       "-s " + rrdStart,
                                       "-e " + rrdEnd)[2]
                for value in reversed(values):
                    value = value[0]
                    if value is not None:
                        break
                if value is None:
                    value = 0
                    log.debug("Unable to fetch %s for %s", rrdName, self._devId)

                log.debug("RRD %s = %s", rrdName, value)
                vars[rrdName] = value

            try:
                result = eval(expression, vars)
            except Exception, e:
                log.exception("Expression %s failed:", expression)
                continue

            log.info("Result of %s --> %s", expression, result)

            dpPath = os.path.join(perfDir, datapoint['path'])
            min = datapoint['minv']
            max = datapoint['maxv']
            value = self._dataService.writeRRD(dpPath, result,
                datapoint['rrdType'], datapoint['rrdCmd'],
                min=datapoint['minv'], max=datapoint['maxv'])
        
        return defer.succeed("Yay!")

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

