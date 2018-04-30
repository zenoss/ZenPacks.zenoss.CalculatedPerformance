##############################################################################
#
# Copyright (C) Zenoss, Inc. 2017-2018, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

"""Tests for AggregatingDataSource."""

# Zenoss Imports
from Products.ZenModel.BasicDataSource import BasicDataSource
from Products.ZenModel.FileSystem import FileSystem
from Products.ZenTestCase.BaseTestCase import BaseTestCase

# PythonCollector Imports
from ZenPacks.zenoss.PythonCollector.datasources.PythonDataSource \
    import PythonDataSource

# CalculatedPerformance Imports
from ZenPacks.zenoss.CalculatedPerformance.datasources.AggregatingDataSource \
    import AggregatingDataSource


class TestAggregatingDataSource(BaseTestCase):
    """Test suite for AggregatingDataSource."""

    def test_getCycleTime(self):
        deviceclass = self.dmd.Devices.createOrganizer(
            "/Test/CalculatedPerformance")
        deviceclass.setZenProperty("zCollectorClientTimeout", 20)

        # Basis datasources.
        deviceclass.manage_addRRDTemplate("FileSystem")
        basis_template = deviceclass.rrdTemplates._getOb("FileSystem")

        command_ds = BasicDataSource("command")
        basis_template.datasources._setObject(command_ds.id, command_ds)
        command_ds = basis_template.datasources._getOb(command_ds.id)
        command_ds.sourcetype = "COMMAND"
        command_ds.cycletime = 10
        command_ds.manage_addRRDDataPoint("command")

        python_ds = PythonDataSource("python")
        basis_template.datasources._setObject(python_ds.id, python_ds)
        python_ds = basis_template.datasources._getOb(python_ds.id)
        python_ds.cycletime = "${here/zCollectorClientTimeout}"
        python_ds.manage_addRRDDataPoint("python")

        # Aggregating datasources.
        deviceclass.manage_addRRDTemplate("Device")
        agg_template = deviceclass.rrdTemplates._getOb("Device")

        agg_ds1 = AggregatingDataSource("agg1")
        agg_template.datasources._setObject(agg_ds1.id, agg_ds1)
        agg_ds1 = agg_template.datasources._getOb(agg_ds1.id)
        agg_ds1.targetMethod = "os.filesystems"
        agg_ds1.targetDataSource = "command"
        agg_ds1.targetDataPoint = "command"
        agg_ds1.useBasisInterval = False
        agg_ds1.cycletime = 30

        agg_ds2 = AggregatingDataSource("agg2")
        agg_template.datasources._setObject(agg_ds2.id, agg_ds2)
        agg_ds2 = agg_template.datasources._getOb(agg_ds2.id)
        agg_ds2.targetMethod = "os.filesystems"
        agg_ds2.targetDataSource = "python"
        agg_ds2.targetDataPoint = "python"
        agg_ds2.useBasisInterval = True
        agg_ds2.cycletime = 40

        # Device
        device = deviceclass.createInstance("TestCalculatedPerformance")
        device.setPerformanceMonitor("localhost")

        # Members
        fs1 = FileSystem("boot")
        device.os.filesystems._setObject(fs1.id, fs1)
        fs2 = FileSystem("root")
        device.os.filesystems._setObject(fs2.id, fs2)

        # Sanity checks.
        self.assertEqual(command_ds.cycletime, 10)
        self.assertEqual(python_ds.getCycleTime(device), 20)

        # useBasisInterval = False
        self.assertEqual(agg_ds1.getCycleTime(device), 30)

        # useBasisInterval = True
        self.assertEqual(agg_ds2.getCycleTime(device), 20)

        # minimumInterval
        agg_ds2.minimumInterval = None
        self.assertEqual(agg_ds2.getCycleTime(device), 20)
        agg_ds2.minimumInterval = 1
        self.assertEqual(agg_ds2.getCycleTime(device), 20)
        agg_ds2.minimumInterval = 40
        self.assertEqual(agg_ds2.getCycleTime(device), 40)
        agg_ds2.minimumInterval = None

        # maximumInterval
        agg_ds2.maximumInterval = None
        self.assertEqual(agg_ds2.getCycleTime(device), 20)
        agg_ds2.maximumInterval = 40
        self.assertEqual(agg_ds2.getCycleTime(device), 20)
        agg_ds2.maximumInterval = 1
        self.assertEqual(agg_ds2.getCycleTime(device), 1)
        agg_ds2.maximumInterval = None
