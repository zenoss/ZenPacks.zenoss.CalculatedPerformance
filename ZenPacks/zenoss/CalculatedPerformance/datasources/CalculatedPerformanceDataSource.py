##############################################################################
#
# Copyright (C) Zenoss, Inc. 2011-2017, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

"""
Custom datasource to calculate a datapoint based on existing RRD
datapoints.
"""

import cgi
import time
import sys

from AccessControl import ClassSecurityInfo
from Products.ZenModel.BasicDataSource import BasicDataSource
from Products.ZenModel import RRDDataSource
from Products.ZenModel.ZenPackPersistence import ZenPackPersistence
from Products.ZenUtils.Utils import executeStreamCommand
from Products.ZenModel.ZenossSecurity import ZEN_CHANGE_DEVICE
from Products.ZenWidgets import messaging
from ZenPacks.zenoss.PythonCollector.datasources.PythonDataSource import PythonDataSource

from ZenPacks.zenoss.CalculatedPerformance import (
    operations, USE_BASIS_INTERVAL, MINIMUM_INTERVAL, MAXIMUM_INTERVAL,)


class CalculatedPerformanceDataSource(PythonDataSource):
    ZENPACKID = 'ZenPacks.zenoss.CalculatedPerformance'

    sourcetypes = ('Calculated Performance',)
    sourcetype = 'Calculated Performance'

    # Collection plugin for this type.
    plugin_classname = 'ZenPacks.zenoss.CalculatedPerformance.dsplugins.DerivedDataSourceProxyingPlugin'

    eventClass = '/Perf'

    description = ''
    expression = ''
    extraContexts = []
    targetAsRate = False
    # we don't use oid but it is defined in basicdatasource so we need it here
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
        """
        Make sure there is exactly one datapoint and that it has the same name
        as the datasource. From SimpleRRDDataSource.
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

    security.declareProtected(ZEN_CHANGE_DEVICE, 'manage_testDataSource')
    def manage_testDataSource(self, testDevice, REQUEST):
        ''' Test the datasource by executing the command and outputting the
        non-quiet results.
        '''
        # set up the output method for our test
        out = REQUEST.RESPONSE

        def write(lines):
            ''' Output (maybe partial) result text.
            '''
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

        # use our input and output to call the testDataSource Method
        errorLog = messaging.IMessageSender(self).sendToBrowser
        return self.testDataSourceAgainstDevice(testDevice,
                                                REQUEST,
                                                write,
                                                errorLog)

    def testDataSourceAgainstDevice(self, testDevice, REQUEST, write, errorLog):
        """
        Does the majority of the logic for testing a datasource against the device
        @param string testDevice The id of the device we are testing
        @param Dict REQUEST the browers request
        @param Function write The output method we are using to stream the result of the command
        @parma Function errorLog The output method we are using to report errors
        """
        out = REQUEST.RESPONSE
        # Determine which device to execute against
        device = None
        if testDevice:
            # Try to get specified device
            device = self.findDevice(testDevice)
            if not device:
                errorLog(
                    'No device found',
                    'Cannot find device matching %s.' % testDevice,
                    priority=messaging.WARNING
                )
                return self.callZenScreen(REQUEST)
        elif hasattr(self, 'device'):
            # ds defined on a device, use that device
            device = self.device()
        elif hasattr(self, 'getSubDevicesGen'):
            # ds defined on a device class, use any device from the class
            try:
                device = self.getSubDevicesGen().next()
            except StopIteration:
                # No devices in this class, bail out
                pass
        if not device:
            errorLog(
                'No Testable Device',
                'Cannot determine a device against which to test.',
                priority=messaging.WARNING
            )
            return self.callZenScreen(REQUEST)

        # Get the command to run
        command = self.getCommand(device)
        header = ''
        footer = ''
        # Render
        if REQUEST.get('renderTemplate', True):
            header, footer = self.commandTestOutput().split('OUTPUT_TOKEN')

        out.write(str(header))
        write("Executing command\n%s\n   against %s" % (command, device.id))
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
