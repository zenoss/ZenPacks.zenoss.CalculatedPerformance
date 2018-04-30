##############################################################################
#
# Copyright (C) Zenoss, Inc. 2014-2018, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

from Globals import InitializeClass
from AccessControl import ClassSecurityInfo

from Products.ZenModel.RRDDataSource import RRDDataSource
from Products.ZenModel.ZenossSecurity import ZEN_MANAGE_DMD
from Products.ZenUtils.FunctionCache import FunctionCache
from Products.Zuul.utils import safe_hasattr

from ZenPacks.zenoss.CalculatedPerformance import (
    operations, USE_BASIS_INTERVAL, MINIMUM_INTERVAL, MAXIMUM_INTERVAL,)
from ZenPacks.zenoss.CalculatedPerformance.AggregatingDataPoint \
    import AggregatingDataPoint
from ZenPacks.zenoss.CalculatedPerformance.utils import dotTraverse
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
    plugin_classname = ('ZenPacks.zenoss.CalculatedPerformance.dsplugins.'
                        'DerivedDataSourceProxyingPlugin')

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
            "Aggregation of {ds}_{dp}:{rra} over {method}".format(
                ds=self.targetDataSource,
                dp=self.targetDataPoint,
                rra=self.targetRRA,
                method=self.targetMethod)

        return description

    def getCycleTime(self, context):
        """Return collection interval for given context."""
        if self.useBasisInterval:
            cycletime = self.getTargetCycleTime(context)
            if cycletime is not None:
                # Enforce user-configured minimum and maximum bounds when
                # using the basis interval. By default minimumInterval and
                # maximumInterval are None which results in
                # the basis interval being used regardless of its value.
                return operations._bound(
                    minValue=self.minimumInterval,
                    value=cycletime,
                    maxValue=self.maximumInterval)

        return super(AggregatingDataSource, self).getCycleTime(context)

    @FunctionCache("getTargetCycleTime", cache_miss_marker=-1, default_timeout=300)
    def getTargetCycleTime(self, context):
        """Return cycletime of basis datasources."""
        for member in dotTraverse(context, self.targetMethod or '') or []:
            for template in member.getRRDTemplates():
                datasource = template.datasources._getOb(
                    self.targetDataSource, None)

                if datasource:
                    if datasource.aqBaseHasAttr("getCycleTime"):
                        return int(datasource.getCycleTime(member))
                    elif datasource.aqBaseHasAttr("cycletime"):
                        return int(datasource.cycletime)

    security.declareProtected(ZEN_MANAGE_DMD, 'manage_addRRDDataPoint')
    def manage_addRRDDataPoint(self, id, REQUEST=None):
        """Add a new RRDDataPoint object to this datasource."""
        if not id:
            return self.callZenScreen(REQUEST)

        # TODO: refactor core to use some sort of factory for this junk.
        # This is all cut & paste code from the base class with
        # the exception of the object creation.
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
