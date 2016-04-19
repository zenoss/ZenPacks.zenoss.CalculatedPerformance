#
# Copyright (C) Zenoss, Inc. 2014, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
from Products.Zuul import IInfo
from ZenPacks.zenoss.CalculatedPerformance.datasources import CalculatedPerformanceDataSource
from zope.component import adapts
from zope.interface import implements
from ZenPacks.zenoss.CalculatedPerformance import ElementPool
from ZenPacks.zenoss.CalculatedPerformance.AggregatingDataPoint import AggregatingDataPoint
from ZenPacks.zenoss.CalculatedPerformance.datasources.AggregatingDataSource import AggregatingDataSource
from ZenPacks.zenoss.CalculatedPerformance.interfaces import IAggregatingDataSourceInfo, IElementPoolInfo, \
    IAggregatingDataPointInfo, ICalculatedPerformanceDataSourceInfo

from Products.Zuul.infos import ProxyProperty
from Products.Zuul.infos.component import ComponentInfo
from Products.Zuul.infos.template import RRDDataSourceInfo, DataPointInfo


class AggregatingDataSourceInfo(RRDDataSourceInfo):
    """
    Defines API access for this datasource.
    """

    implements(IAggregatingDataSourceInfo)
    adapts(AggregatingDataSource)

    cycletime = ProxyProperty('cycletime')

    method = ProxyProperty('targetMethod')
    datasource = ProxyProperty('targetDataSource')
    datapoint = ProxyProperty('targetDataPoint')
    rra = ProxyProperty('targetRRA')
    asRate = ProxyProperty('targetAsRate')

    testable = False
    debug = ProxyProperty('debug')


class CalculatedPerformanceDataSourceInfo(RRDDataSourceInfo):
    implements(ICalculatedPerformanceDataSourceInfo)
    adapts(CalculatedPerformanceDataSource)

    cycletime = ProxyProperty('cycletime')

    description = ProxyProperty('description')
    expression = ProxyProperty('expression')
    asRate = ProxyProperty('targetAsRate')
    debug = ProxyProperty('debug')

    testable = False


class AggregatingDataPointInfo(DataPointInfo):
    """
    Defines API access for this datasource.
    """

    implements(IAggregatingDataPointInfo)
    adapts(AggregatingDataPoint)

    operation = ProxyProperty('operation')
    arguments = ProxyProperty('arguments')


class ElementPoolInfo(ComponentInfo):
    implements(IElementPoolInfo)
    adapts(ElementPool)

    def __init__(self, context):
        super(ElementPoolInfo, self).__init__(context)
        self._members = None

    def _loadMembers(self):
        if self._members is None:
            self._members = [IInfo(obj) for obj in self._object.getElements()]

    @property
    def numberOfMembers(self):
        self._loadMembers()
        return len(self._members)

    @property
    def members(self):
        self._loadMembers()
        return self._members
