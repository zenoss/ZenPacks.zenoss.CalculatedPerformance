######################################################################
#
# Copyright 2011 Zenoss, Inc.  All Rights Reserved.
#
######################################################################

__doc__ = """zencalcperfd
Compute the values for a new datasource based on existing RRD values.

Note
There is the possibility of a race condition based on when data is written,
and we are handling it by writing out the data every minute.
"""

import logging
import os.path

from twisted.internet import defer

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
#                                        SubTaskSplitter,\

from Products.ZenUtils.observable import ObservableMixin
from Products.ZenUtils.Utils import unused, zenPath

from Products.ZenCollector.services.config import DeviceProxy
unused(DeviceProxy)

from ZenPacks.zenoss.CalculatedPerformance.services.CalcPerfConfig import getVarNames

COLLECTOR_NAME = "zencalcperfd"

log = logging.getLogger("zen.%s" % COLLECTOR_NAME)

class SimpleObject(object):
    """
    Simple class that can have arbitrary attributes assigned to it.
    """


def createDeviceDictionary(deviceProxy):
    """
    Returns a dictionary of simple objects suitable for passing into eval().
    """
    # Add in default methods
    vars = {
        'pct': pct,
        'avg': avg,
    }

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


#class CalcPerfSplitter(SubTaskSplitter):

# These methods will be added to the evaluation locals for the calculated expressions
def pct(numerator, denominator):
    """
    This method calculates the percentage of the numerator and denominator, which
    can be either numerics or lists of numerics. None is filtered out.
    The value 0.0 is returned if the denominatorList sums to zero.

    sum(numerator) / sum(denominator) * 100.0
    """
    bottom = denominator if isinstance(denominator, (list, tuple)) else [denominator]
    denominator = sum(x for x in bottom if x is not None)
    if denominator == 0.0:
        return 0.0

    top = numerator if isinstance(numerator, (list, tuple)) else [numerator]
    numerator = sum(x for x in top if x is not None)

    return numerator / denominator * 100.0

def avg(dpList):
    """
    Average a list of datapoints.  A list with no non-None items has an average of zero.
    """
    if not dpList:
        return 0.0

    dpList = [x for x in dpList if x is not None]
    if not dpList:
        return 0.0

    return sum(dpList) / len(dpList)


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
# TODO: get the correct interval scheduling stuff figured out
        #self.interval = scheduledIntervalSeconds
        self.interval = 60
        
        self._device = taskConfig
        self._devId = deviceId
        self._manageIp = self._device.manageIp

        self._dataService = zope.component.queryUtility(IDataService)
        self._eventService = zope.component.queryUtility(IEventService)
        self._preferences = zope.component.queryUtility(ICollectorPreferences, COLLECTOR_NAME)

        self._collector = zope.component.queryUtility(ICollector)
        self._lastErrorMsg = ''

    def doTask(self):
        # TODO: set up so that we use deferreds to get better concurrency

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

            self._fetchRrdValues(rrdNames, vars, rrd_paths)

            try:
                result = eval(expression, vars)
            except Exception:
                log.exception("Expression %s failed:", expression)
                continue

            path = datapoint['path']
            log.debug("Result of %s --> %s %s", expression, result, path)
            self._dataService.writeRRD(path, result,
                datapoint['rrdType'], datapoint['rrdCmd'],
                #cycleTime=self.interval,
                cycleTime=60,
                min=datapoint['minv'], max=datapoint['maxv'])

        return defer.succeed("Gathered datapoint information")

    def _fetchRrdValues(self, rrdNames, vars, rrd_paths):
        # TODO: cache the values during the run so that we do less IO

        # Grab all the data for the last 10 minutes and grab the latest
        rrdStart = 'now-600s'
        rrdEnd = 'now'
        perfDir = zenPath('perf')

        log.debug("Perf to get: %s", rrdNames)
        for rrdName in rrdNames:
            filePath = os.path.join(perfDir, rrd_paths[rrdName])

            try:
                values = self._dataService.readRRD(filePath,
                                       'AVERAGE',
                                       "-s " + rrdStart,
                                       "-e " + rrdEnd)[2]
            except Exception, e:
                log.debug("Unable to read RRD file %s: %s", filePath, e)
                vars[rrdName] = None
                continue

            for value in reversed(values):
                value = value[0]
                if value is not None:
                    break

            if value is None:
                value = 0
                log.debug("Unable to fetch %s for %s", rrdName, self._devId)

            log.debug("RRD %s = %s", rrdName, value)
            vars[rrdName] = value

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
    #myTaskSplitter = CalcPerfSplitter(myTaskFactory)
    myTaskSplitter = SimpleTaskSplitter(myTaskFactory)
    daemon = CollectorDaemon(myPreferences, myTaskSplitter)
    daemon.run()

