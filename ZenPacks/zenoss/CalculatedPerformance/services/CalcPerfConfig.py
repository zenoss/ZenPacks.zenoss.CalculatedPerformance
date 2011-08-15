######################################################################
#
# Copyright 2007 Zenoss, Inc.  All Rights Reserved.
#
######################################################################

from Products.ZenHub.services.PerformanceConfig import PerformanceConfig
import transaction
import logging
log = logging.getLogger("zenhub")

from twisted.spread import pb
class DeviceCalcPerf(pb.Copyable, pb.RemoteCopy):
    device = None
    txs = ()
    thresholds = ()
pb.setUnjellyableForClass(DeviceCalcPerf, DeviceCalcPerf)

class CalcPerf(PerformanceConfig):

    def remote_getCalcPerfs(self, devId=None):
        log.debug('CalcPerf.remote_getCalcPerfs')
        result = []
        for dev in self.config.devices():
            if not devId or devId == dev.id:
                 dev = dev.primaryAq()
                 cfg = self.getDeviceCalcPerfs(dev)
                 if cfg:
                     result.append(cfg)
        return result

    def getDeviceCalcPerfs(self, dev):
        result = None
        log.debug('Getting webtxs for %s' % dev.id)
        if not dev.monitorDevice():
            log.debug('CalcPerf: not monitoring %s' % dev.id)
            return result
        cfg = DeviceCalcPerf()
        cfg.device = dev.id
        cfg.txs = []
        cfg.thresholds = []
        for templ in dev.getRRDTemplates():
            dataSources = templ.getRRDDataSources('CalcPerf')
            for ds in [d for d in dataSources if d.enabled]:
                result = cfg
                points = [{'id': dp.id, 
                           'path': '/'.join((dev.rrdPath(), dp.name())),
                           'rrdType': dp.rrdtype,
                           'rrdCmd': dp.createCmd,
                           'minv': dp.rrdmin,
                           'maxv': dp.rrdmax,
                           }
                          for dp in ds.getRRDDataPoints()]
                cfg.thresholds += dev.getThresholdInstances('CalcPerf')
                cfg.txs.append({ 'devId': dev.id,
                                 'manageIp': dev.manageIp,
                                 'timeout': ds.webTxTimeout,
                                 'datasource': ds.id,
                                 'datapoints': points,
                                 'cycletime': ds.cycletime or '',
                                 'compId': ds.component or '',
                                 'eventClass': ds.eventClass or '',
                                 'severity': ds.severity or 0,
                                 'userAgent': ds.userAgent or '',
                                 'initialUrl': ds.initialURL or '',
                                 'command': ds.getCommand(dev) or '',
                                 })
        log.debug('%s webtxs for %s', len(cfg.txs), dev.id)
        return result


    def getDeviceConfig(self, device):
        "How to get the config for a device"
        return self.getDeviceCalcPerfs(device)


    def sendDeviceConfig(self, listener, config):
        "How to send the config to a device, probably via callRemote"
        return listener.callRemote('updateDeviceConfig', [config])

