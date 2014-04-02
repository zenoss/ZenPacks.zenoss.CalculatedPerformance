##############################################################################
#
# Copyright (C) Zenoss, Inc. 2014, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

from Products.ZenUtils.Ext import DirectRouter
from Products import Zuul
from Products.ZenUtils.Ext import DirectResponse

class ElementPoolRouter(DirectRouter):
    def _getFacade(self):
        return Zuul.getFacade('elementpool',self.context)

    def getMembers(self, uid, keys=None):
        facade = self._getFacade()
        if keys is None:
            keys = ['severity', 'monitor', 'hidden', 'leaf', 'uid', 'text', 'id', 'path', 'iconCls', 'uuid', 'name', 'meta_type']
        data = facade.getMembers(uid)
        return DirectResponse(data=Zuul.marshal(data, keys), totalCount=len(data),
                              hash=len(data))




