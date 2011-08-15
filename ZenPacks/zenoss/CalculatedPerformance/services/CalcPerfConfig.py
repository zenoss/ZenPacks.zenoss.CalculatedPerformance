######################################################################
#
# Copyright 2009-2010 Zenoss, Inc.  All Rights Reserved.
#
######################################################################

import transaction

from Acquisition import aq_base
from Products.CMFCore.utils import getToolByName
from Products.ZenCollector.services.config import CollectorConfigService

from ZenPacks.zenoss.CalculatedPerformance.datasources.CalculatedPerformanceDataSource import CalculatedPerformanceDataSource

DSTYPE = CalculatedPerformance.sourcetype

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

class CalcPerfConfig(CollectorConfigService):

    def _createDeviceProxy(self, device):
        proxy = CollectorConfigService._createDeviceProxy(self, device)

        # The event daemon keeps a persistent connection open, so this cycle
        # interval will only be used if the connection is lost... for now, it
        # doesn't need to be configurable.
        proxy.configCycleInterval =  5 * 60 # seconds

        proxy.datapoints = []
        proxy.thresholds = []

        perfServer = device.getPerformanceServer()

        for component in [device] + device.getMonitoredComponents():
            self._getDataPoints(proxy, component, component.device().id, component.id, perfServer)
            proxy.thresholds += component.getThresholdInstances(DSTYPE)

        return proxy

    def _getDataPoints(self, proxy, deviceOrComponent, deviceId, componentId, perfServer):
        for template in deviceOrComponent.getRRDTemplates():
            dataSources = [ds for ds
                           in template.getRRDDataSources(DSTYPE)
                           if ds.enabled]

            obj_attrs = {}

            for att in re.findall(r"[A-Za-z][A-Za-z0-9_\.]*", ds.formula):
                value = dotTraverse(deviceOrComponent, att)
                if value is not None:
                    obj_attrs[att] = value

            for ds in dataSources:
                dp = ds.datapoints()[0]
                dpInfo = dict(
                    devId=deviceId,
                    compId=componentId,
                    dsId=ds.id,
                    dpId=dp.id,
                    formula=ds.formula,
                    obj_attrs=obj_attrs,
                    path='/'.join((deviceOrComponent.rrdPath(), dp.name())),
                    rrdType=dp.rrdtype,
                    rrdCmd=dp.getRRDCreateCommand(perfServer),
                    minv=dp.rrdmin,
                    maxv=dp.rrdmax,)

                proxy.datapoints.append(dpInfo)

