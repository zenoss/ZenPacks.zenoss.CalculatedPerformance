#
# Copyright (C) Zenoss, Inc. 2014, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#

import logging
log = logging.getLogger('zen.CalculatedPerformance')

import Globals

from Products.ZenModel.Device import Device
from Products.ZenModel.ZenPack import ZenPack as ZenPackBase
from Products.ZenRelations.RelSchema import ToManyCont, ToOne
from Products.ZenUtils.Utils import unused
from Products.Zuul.interfaces import ICatalogTool
from ZenPacks.zenoss.CalculatedPerformance.ElementPool import ElementPool

unused(Globals)


ZENPACK_NAME = 'ZenPacks.zenoss.CalculatedPerformance'

# Define new device relations.
NEW_DEVICE_RELATIONS = (
    ('aggregatingPools', 'ElementPool', ToManyCont, 'parentDevice', ToOne, Device),
)

NEW_COMPONENT_TYPES = (
    ZENPACK_NAME + '.ElementPool.ElementPool',
)

# Add new relationships to Device if they don't already exist.
for relname, modname, myRelType, theirRelName, theirRelType, containingClass in NEW_DEVICE_RELATIONS:
    if relname not in (x[0] for x in containingClass._relations):
        containingClass._relations += (
            (relname, myRelType(theirRelType,
                                '.'.join((ZENPACK_NAME, modname)),
                                theirRelName)),
        )


class ZenPack(ZenPackBase):
    """
    ZenPack loader that handles custom installation and removal tasks.
    """
    packZProperties = [('zAggregatorCollectionInterval', 300, 'int')]

    def install(self, app):
        super(ZenPack, self).install(app)

        log.info('Adding ElementPool relationships to existing devices/components')
        self._buildDeviceRelations()

    def remove(self, app, leaveObjects=False):
        if not leaveObjects:
            log.info('Removing all ElementPool components')
            cat = ICatalogTool(app.zport.dmd)
            for brain in cat.search(types=NEW_COMPONENT_TYPES):
                component = brain.getObject()
                component.getPrimaryParent()._delObject(component.id)

            # Remove our relations additions.
            for relname, _, _, _, _, containingClass in NEW_DEVICE_RELATIONS:
                containingClass._relations = tuple(
                    [x for x in containingClass._relations if x[0] != relname])

            log.info('Removing ElementPool device/component relationships')
            self._buildDeviceRelations()

        super(ZenPack, self).remove(app, leaveObjects=leaveObjects)

    def _buildDeviceRelations(self):
        for d in self.dmd.Devices.getSubDevicesGen():
            d.buildRelations()

def addAggregatingPool(device, id):
    instance = ElementPool(id)
    device.aggregatingPools._setObject(id, instance)
    instance = device.aggregatingPools._getOb(id)
    instance.index_object()
    return instance
