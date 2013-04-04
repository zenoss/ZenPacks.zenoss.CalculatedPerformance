##############################################################################
#
# Copyright (C) Zenoss, Inc. 2011, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

from zope.interface import implements
from Products.Zuul.infos import ProxyProperty
from Products.Zuul.infos.template import RRDDataSourceInfo
from ZenPacks.zenoss.CalculatedPerformance.interfaces import ICalculatedPerformanceDataSourceInfo


class CalculatedPerformanceDataSourceInfo(RRDDataSourceInfo):
    implements(ICalculatedPerformanceDataSourceInfo)

    description = ProxyProperty('description')
    expression = ProxyProperty('expression')
    cycletime = ProxyProperty('cycletime')

    @property
    def testable(self):
        """
        Tells the UI that we can test this datasource against a specific device
        """
        return True
