######################################################################
#
# Copyright 2011 Zenoss, Inc.  All Rights Reserved.
#
######################################################################

from zope.interface import implements
from Products.Zuul.infos import ProxyProperty
from Products.Zuul.infos.template import RRDDataSourceInfo
from ZenPacks.zenoss.CalculatedPerformance.interfaces import ICalculatedPerformanceDataSourceInfo


class CalculatedPerformanceDataSourceInfo(RRDDataSourceInfo):
    implements(ICalculatedPerformanceDataSourceInfo)

    expression = ProxyProperty('expression')

    @property
    def testable(self):
        """
        Tells the UI that we can test this datasource against a specific device
        """
        return True

