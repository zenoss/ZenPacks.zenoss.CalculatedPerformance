##############################################################################
#
# Copyright (C) Zenoss, Inc. 2011-2018, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

"""Custom datasource to calculate a datapoint based
on existing RRD datapoints.

"""

import cgi
import time
import sys

from AccessControl import ClassSecurityInfo

from Products.ZenModel.BasicDataSource import BasicDataSource
from Products.ZenUtils.FunctionCache import FunctionCache
from Products.ZenUtils.Utils import executeStreamCommand
from Products.ZenModel.ZenossSecurity import ZEN_CHANGE_DEVICE
from Products.ZenWidgets import messaging

from ZenPacks.zenoss.PythonCollector.datasources.PythonDataSource \
    import PythonDataSource

from ZenPacks.zenoss.CalculatedPerformance import (
    operations, USE_BASIS_INTERVAL, MINIMUM_INTERVAL, MAXIMUM_INTERVAL,)
from ZenPacks.zenoss.CalculatedPerformance.utils import getVarNames


class CalculatedPerformanceDataSource(PythonDataSource):
    """Notes about parameters:

    The 'expression' parameter is literally an expression that is evaluated
    by eval(), with a dictionary that contains metrics and model attributes
    of the device or component context. Values from the model will be looked
    up in zenhub before the config is sent to zenpython. Metrics will be
    queried each time the single datapoint in the datasource is measured.

    The 'extraContexts' parameter is a list of strings which allow other
    components or the device to provide the metrics or model attributes
    referred to by the expression.

    Examples of valid 'extraContexts' entries if the device is in
    the /ZenossRM device class, which has relationships named 'durableQueues'
    and 'zenEventDs', and the context of the datasource is
    a Collector component, which has a 'hub' toOne relationship.

    'device' :
      the special case

    'device/durableQueues/zenoss.queues.zep.rawevents' :
      the component whose id is 'zenoss.queues.zep.rawevents' in the
      'durableQueues' relationship. Since one of the modeler plugins for
      devices in this device class populate this rel, and a zenoss system
      always has one of the above queues, this path returns something.

    'device/zenEventDs/0' :
      the component in this relationship. the modeler plugins for
      devices in this device class populate this rel with 1 ZenEventD
      component in all cases. It is a toMany containing relationship, however.

    'hub' :
      the ZenHub component at the other end of
      the Collectors 'hub' relationship

    If a datapoint or model attribute exists on more than one thing
    in the list of extraContexts the later thing in the list of extraContexts
    will 'win'; if something exists on both one of the extraContexts
    and the context (device or component to which the template containing
    the datasource is bound), the context will 'win'.

    """
    ZENPACKID = 'ZenPacks.zenoss.CalculatedPerformance'

    sourcetypes = ('Calculated Performance',)
    sourcetype = 'Calculated Performance'

    # Collection plugin for this type.
    plugin_classname = ('ZenPacks.zenoss.CalculatedPerformance.dsplugins.'
                        'DerivedDataSourceProxyingPlugin')

    eventClass = '/Perf'

    description = ''
    expression = ''
    extraContexts = []
    targetAsRate = False
    # We don't use oid but it is defined in basic datasource,
    # so we need it here.
    oid = ''
    usessh = False
    parser = ""
    debug = False
    useBasisInterval = USE_BASIS_INTERVAL
    minimumInterval = MINIMUM_INTERVAL
    maximumInterval = MAXIMUM_INTERVAL

    _properties = BasicDataSource._properties + (
        {'id': 'description', 'type': 'string', 'mode': 'w'},
        {'id': 'expression', 'type': 'string', 'mode': 'w'},
        {'id': 'extraContexts', 'type': 'lines', 'mode': 'w'},
        {'id': 'targetAsRate', 'type': 'boolean', 'mode': 'w'},
        {'id': 'cycletime', 'type': 'int', 'mode': 'w'},
        {'id': 'debug', 'type': 'boolean', 'mode': 'w'},
        {'id': 'useBasisInterval', 'type': 'boolean', 'mode': 'w'},
        {'id': 'minimumInterval', 'type': 'int', 'mode': 'w'},
        {'id': 'maximumInterval', 'type': 'int', 'mode': 'w'},
    )

    security = ClassSecurityInfo()

    def addDataPoints(self):
        """Make sure there is exactly one datapoint and that it has
        the same name as the datasource. From SimpleRRDDataSource.

        """
        dpid = self.prepId(self.id)
        remove = [d for d in self.datapoints() if d.id != dpid]
        for dp in remove:
            self.datapoints._delObject(dp.id)

        if not self.datapoints._getOb(dpid, None):
            self.manage_addRRDDataPoint(dpid)

    def getDescription(self):
        description = ''
        if self.expression:
            description = self.expression
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

        return super(
            CalculatedPerformanceDataSource, self).getCycleTime(context)

    @FunctionCache("getTargetCycleTime", cache_miss_marker=-1, default_timeout=300)
    def getTargetCycleTime(self, context):
        """Return cycletime of basis datasources."""
        datasources_by_varname = {}
        for template in context.getRRDTemplates():
            for datasource in template.datasources():
                for datapoint in datasource.datapoints():
                    datasources_by_varname[datapoint.id] = datasource
                    datasources_by_varname[datapoint.name()] = datasource

        cycletimes = set()

        for varname in getVarNames(self.expression):
            datasource = datasources_by_varname.get(varname)
            if not datasource:
                continue

            # Some types of datasources such as PythonDataSource and
            # UCSDataSource implement a getCycleTime(context) method that
            # provides a context-specific interval instead of the static
            # cycletime property used by most other types of datasources. We
            # want to prefer the getCycleTime method's result to the cycletime
            # value because it will actually be the real collection interval
            # of the basis datasource.
            if datasource.aqBaseHasAttr("getCycleTime"):
                cycletimes.add(int(datasource.getCycleTime(context)))
            elif datasource.aqBaseHasAttr("cycletime"):
                cycletimes.add(int(datasource.cycletime))

        if cycletimes:
            # It's common for multiple basis datapoints to be used in the
            # expression. In cases where different datapoints in the
            # expression have different intervals, we'll choose the shortest
            # interval.
            return min(cycletimes)

    security.declareProtected(ZEN_CHANGE_DEVICE, 'manage_testDataSource')
    def manage_testDataSource(self, testDevice, REQUEST):
        """Test the datasource by executing the command and
        outputting the non-quiet results.

        """
        # Set up the output method for our test.
        out = REQUEST.RESPONSE

        def write(lines):
            """Output (maybe partial) result text."""
            # Looks like firefox renders progressive output more smoothly
            # if each line is stuck into a table row.
            startLine = '<tr><td class="tablevalues">'
            endLine = '</td></tr>\n'
            if out:
                if not isinstance(lines, list):
                    lines = [lines]
                for l in lines:
                    if not isinstance(l, str):
                        l = str(l)
                    l = l.strip()
                    l = cgi.escape(l)
                    l = l.replace('\n', endLine + startLine)
                    out.write(startLine + l + endLine)

        # Use our input and output to call the testDataSource method.
        errorLog = messaging.IMessageSender(self).sendToBrowser
        return self.testDataSourceAgainstDevice(
            testDevice, REQUEST, write, errorLog)

    def testDataSourceAgainstDevice(
            self, testDevice, REQUEST, write, errorLog):
        """Does the majority of the logic for testing
        a datasource against the device.

        @param string testDevice: The id of the device we are testing.
        @param dict REQUEST: The browers request.
        @param function write: The output method we are using to
            stream the result of the command.
        @parma function errorLog: The output method we are using
            to report errors.

        """
        out = REQUEST.RESPONSE
        # Determine which device to execute against.
        device = None
        if testDevice:
            # Try to get specified device.
            device = self.findDevice(testDevice)
            if not device:
                errorLog(
                    'No device found',
                    'Cannot find device matching %s.' % testDevice,
                    priority=messaging.WARNING)

                return self.callZenScreen(REQUEST)
        elif hasattr(self, 'device'):
            # The datasource defined on a device, use that device.
            device = self.device()
        elif hasattr(self, 'getSubDevicesGen'):
            # The datasource defined on a device class,
            # use any device from the class.
            try:
                device = self.getSubDevicesGen().next()
            except StopIteration:
                # No devices in this class, bail out
                pass

        if not device:
            errorLog(
                'No Testable Device',
                'Cannot determine a device against which to test.',
                priority=messaging.WARNING)

            return self.callZenScreen(REQUEST)

        # Get the command to run.
        command = self.getCommand(device)
        header = ''
        footer = ''

        if REQUEST.get('renderTemplate', True):
            header, footer = self.commandTestOutput().split('OUTPUT_TOKEN')

        out.write(str(header))
        write("Executing command\n%s\n against %s" % (command, device.id))
        write('')
        start = time.time()

        try:
            executeStreamCommand(command, write)
        except:
            write('exception while executing command')
            write('type: %s  value: %s' % tuple(sys.exc_info()[:2]))

        write('')
        write('')
        write('DONE in %s seconds' % long(time.time() - start))
        out.write(str(footer))
