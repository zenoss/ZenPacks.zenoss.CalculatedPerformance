##############################################################################
#
# Copyright (C) Zenoss, Inc. 2014-2018, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

import logging

from BTrees.OOBTree import OOSet

from Products.ZenModel.DeviceComponent import DeviceComponent
from Products.ZenModel.ManagedEntity import ManagedEntity
from Products.ZenModel.ZenossSecurity import ZEN_CHANGE_DEVICE
from Products.ZenRelations.RelSchema import ToManyCont, ToOne
from Products.ZenUtils.guid.interfaces import IGUIDManager


LOG = logging.getLogger("zen.ElementPool")


class ElementPool(DeviceComponent, ManagedEntity):

    meta_type = portal_type = "ElementPool"

    members = OOSet()
    monitor = True

    _properties = ManagedEntity._properties + (
        {'id': 'members', 'type': 'lines', 'mode': 'w'},
    )

    _relations = ManagedEntity._relations + (
        (
            'parentDevice', ToOne(
                ToManyCont,
                'Products.ZenModel.Device.Device',
                'aggregatingPools'),
        ),
    )

    # Meta-data: Zope object views and actions.
    factory_type_information = ({
        'actions': ({
            'id': 'perfConf',
            'name': 'Template',
            'action': 'objTemplates',
            'permissions': (ZEN_CHANGE_DEVICE,),
        },),
    },)

    def device(self):
        return self.parentDevice()

    def getElements(self):
        manager = IGUIDManager(self.getDmd())
        memberObjs = []
        for poolmember in self.members:
            obj = manager.getObject(poolmember)
            if obj:
                memberObjs.append(obj)
            else:
                LOG.warn("Stale ElementPool member: %s", poolmember)

        return memberObjs
