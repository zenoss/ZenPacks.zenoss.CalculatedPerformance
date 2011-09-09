######################################################################
#
# Copyright 2011 Zenoss, Inc.  All Rights Reserved.
#
######################################################################

__doc__ = """CalcPerfConfig
Service for the zencalcperfd daemon that finds datasources that are
explicitly computed from existing RRD values.
"""

import re
import logging

log = logging.getLogger('zen.zenhub.service.calcperf')

import Globals
from Products.ZenCollector.services.config import CollectorConfigService

from ZenPacks.zenoss.CalculatedPerformance.datasources.CalculatedPerformanceDataSource import CalculatedPerformanceDataSource

DSTYPE = CalculatedPerformanceDataSource.sourcetype

def dotTraverse(base, path):
    """ 
    Traverse object attributes with a . separating attributes.
    e.g., base=find("deviceId") ; dotTraverse(base, "hw.totalMemory")
        --> 2137460736
    """
    path = path.split(".")
    while len(path) > 0:
        try:
            base = getattr(base, path.pop(0))
        except:
            return None
    return base 


varNameRe = re.compile(r"[A-Za-z][A-Za-z0-9_\.]*")
# Valid keywords available for using in expressions
keywords = ('and', 'or', 'not', 'is', 'in',
            'None', 'if', 'else', 'for', 'map',
            'filter', 'lambda', 'range', 'sum',
            'avg', 'pct', 'min', 'max',

            # These are not keywords, but will be ignored so that lists can be used
            'x', 'y', 'i', 'j')
def getVarNames(expression):
    names = varNameRe.findall(expression)
    return [name for name in names if name not in keywords]


class CalcPerfConfig(CollectorConfigService):

    def _createDeviceProxy(self, device):
        proxy = CollectorConfigService._createDeviceProxy(self, device)

        # The event daemon keeps a persistent connection open, so this cycle
        # interval will only be used if the connection is lost... for now, it
        # doesn't need to be configurable.
        proxy.configCycleInterval =  5 * 60 # seconds

        proxy.datapoints = []
        proxy.thresholds = []

        for component in [device] + device.getMonitoredComponents():
            try:
                self._getDataPoints(proxy, component, component.device().id, component.id)
            except Exception, ex:
                log.warn("Skipping %s component %s because %s",
                         device.id, component.id, str(ex))
                continue
            proxy.thresholds += component.getThresholdInstances(DSTYPE)

        if len(proxy.datapoints) > 0:
            return proxy

    def _getDataPoints(self, proxy, deviceOrComponent, deviceId, componentId):
        allDatapointNames = [d.id for d in deviceOrComponent.getRRDDataPoints()]
        for template in deviceOrComponent.getRRDTemplates():
            dataSources = [ds for ds
                           in template.getRRDDataSources(DSTYPE)
                           if ds.enabled]

            obj_attrs = {}
            rrd_paths = {}

            for ds in dataSources:
                for att in getVarNames(ds.expression):
                    value = dotTraverse(deviceOrComponent, att)
                    if value is not None:
                        obj_attrs[att] = value
                    elif att in allDatapointNames:
                        rrd_paths[att] = deviceOrComponent.getRRDFileName(att)
                    else:
                        raise Exception("Calculated Performance expression "
                            "%s references the variable %s which is not in %s" % (
                            ds.expression, att, allDatapointNames))

                dp = ds.datapoints()[0]

                dpInfo = dict(
                    devId=deviceId,
                    compId=componentId,
                    dsId=ds.id,
                    dpId=dp.id,
                    expression=ds.expression,
                    obj_attrs=obj_attrs,
                    cycletime=dp.cycletime,
                    rrd_paths=rrd_paths,
                    path='/'.join((deviceOrComponent.rrdPath(), dp.name())),
                    rrdType=dp.rrdtype,
                    rrdCmd=dp.getRRDCreateCommand(deviceOrComponent.getPerformanceServer()),
                    minv=dp.rrdmin,
                    maxv=dp.rrdmax,)
                if not dpInfo['rrdCmd']:
                    dpInfo['rrdCmd'] = deviceOrComponent.perfServer().getDefaultRRDCreateCommand()

                proxy.datapoints.append(dpInfo)


if __name__ == '__main__':
    # Import directly if in Avalon
    #from Products.ZenHub.ServiceTester import ServiceTester
    from ZenPacks.zenoss.CalculatedPerformance.ServiceTester import ServiceTester
    from pprint import pprint

    tester = ServiceTester(CalcPerfConfig)
    def printer(proxy):
        pprint(proxy.datapoints)
    tester.printDeviceProxy = printer
    tester.showDeviceInfo()

