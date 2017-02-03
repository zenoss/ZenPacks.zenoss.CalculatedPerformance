#
# Copyright (C) Zenoss, Inc. 2014-2017, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
from Globals import InitializeClass
from AccessControl import ClassSecurityInfo
from Products.ZenModel.RRDDataSource import RRDDataSource
from Products.ZenModel.ZenossSecurity import ZEN_MANAGE_DMD
from Products.Zuul.utils import safe_hasattr
from ZenPacks.zenoss.CalculatedPerformance import (
    operations, USE_BASIS_INTERVAL, MINIMUM_INTERVAL, MAXIMUM_INTERVAL,)
from ZenPacks.zenoss.CalculatedPerformance.AggregatingDataPoint import AggregatingDataPoint
from ZenPacks.zenoss.PythonCollector.datasources.PythonDataSource \
    import PythonDataSource, PythonDataSourcePlugin


AGGREGATOR_SOURCE_TYPE = 'Datapoint Aggregator'


class AggregatingDataSource(PythonDataSource):
    """Aggregates a single datapoint from multiple devices/components"""

    ZENPACKID = 'ZenPacks.zenoss.CalculatedPerformance'

    # Friendly name for your data source type in the drop-down selection.
    sourcetypes = (AGGREGATOR_SOURCE_TYPE,)
    sourcetype = AGGREGATOR_SOURCE_TYPE

    # Collection plugin for this type.
    plugin_classname = 'ZenPacks.zenoss.CalculatedPerformance.dsplugins.DerivedDataSourceProxyingPlugin'

    # Set default values for properties inherited from RRDDataSource.
    eventClass = '/Perf'
    component = "${here/id}"

    # Add default values for custom properties of this datasource.
    targetMethod = 'getElements'
    targetDataSource = ''
    targetDataPoint = ''
    targetRRA = 'AVERAGE'
    targetAsRate = False
    debug = False
    useBasisInterval = USE_BASIS_INTERVAL
    minimumInterval = MINIMUM_INTERVAL
    maximumInterval = MAXIMUM_INTERVAL

    _properties = RRDDataSource._properties + (
        {'id': 'targetMethod', 'type': 'string'},
        {'id': 'targetDataSource', 'type': 'string'},
        {'id': 'targetDataPoint', 'type': 'string'},
        {'id': 'targetRRA', 'type': 'string'},
        {'id': 'targetAsRate', 'type': 'boolean'},
        {'id': 'debug', 'type': 'boolean', 'mode': 'w'},
        {'id': 'useBasisInterval', 'type': 'boolean', 'mode': 'w'},
        {'id': 'minimumInterval', 'type': 'int', 'mode': 'w'},
        {'id': 'maximumInterval', 'type': 'int', 'mode': 'w'},
    )

    security = ClassSecurityInfo()

    def getDescription(self):
        description = self.description or \
            "Aggregation of %s_%s:%s over %s" % \
            (self.targetDataSource, self.targetDataPoint, self.targetRRA, self.targetMethod)
        return description

    security.declareProtected(ZEN_MANAGE_DMD, 'manage_addRRDDataPoint')
    def manage_addRRDDataPoint(self, id, REQUEST=None):
        """
        Add a new RRDDataPoint object to this datasource.
        """
        if not id:
            return self.callZenScreen(REQUEST)

        # TODO: refactor core to use some sort of factory for this junk. This
        # is all cut & paste code from the base class with the exception of
        # of the object creation.
        dp = AggregatingDataPoint(id)
        if safe_hasattr(operations, id):
            dp.operation = id

        self.datapoints._setObject(dp.id, dp)
        dp = self.datapoints._getOb(dp.id)
        if REQUEST:
            if dp:
                url = '%s/datapoints/%s' % (self.getPrimaryUrlPath(), dp.id)
                REQUEST['RESPONSE'].redirect(url)
            return self.callZenScreen(REQUEST)
        return dp


InitializeClass(AggregatingDataSource)
