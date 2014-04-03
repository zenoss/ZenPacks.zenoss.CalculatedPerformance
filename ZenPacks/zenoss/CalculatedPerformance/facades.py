##############################################################################
#
# Copyright (C) Zenoss, Inc. 2014, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

from zope.interface import implements
from Products.Zuul.facades import ZuulFacade
from Products.Zuul.interfaces import IInfo
from ZenPacks.zenoss.CalculatedPerformance.interfaces import IElementPoolFacade


class ElementPoolFacade(ZuulFacade):
    implements(IElementPoolFacade)
    """
    Facade for ElementPool management
    """

    def getMembers(self, uid):
        info = IInfo(self._getObject(uid))
        if hasattr(info, 'members'):
            return info.members
        return []
