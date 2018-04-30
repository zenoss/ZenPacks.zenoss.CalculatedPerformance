##############################################################################
#
# Copyright (C) Zenoss, Inc. 2017-2018, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

"""Tests for CalculatedPerformanceDataSource."""

# Zenoss Imports
from Products.ZenModel.BasicDataSource import BasicDataSource
from Products.ZenTestCase.BaseTestCase import BaseTestCase

# PythonCollector Imports
from ZenPacks.zenoss.PythonCollector.datasources.PythonDataSource \
    import PythonDataSource

# CalculatedPerformance Imports
from ZenPacks.zenoss.CalculatedPerformance.datasources.CalculatedPerformanceDataSource \
    import CalculatedPerformanceDataSource


class TestCalculatedPerformanceDataSource(BaseTestCase):
    """Test suite for CalculatedPerformanceDataSource."""

    def test_getCycleTime(self):
        deviceclass = self.dmd.Devices.createOrganizer(
            "/Test/CalculatedPerformance")
        deviceclass.setZenProperty("zCollectorClientTimeout", 20)

        deviceclass.manage_addRRDTemplate("Device")
        template = deviceclass.rrdTemplates._getOb("Device")

        # Basis datasources.
        basis_ds1 = BasicDataSource("basis1")
        template.datasources._setObject(
            basis_ds1.id, basis_ds1)
        basis_ds1 = template.datasources._getOb(basis_ds1.id)
        basis_ds1.sourcetype = "COMMAND"
        basis_ds1.cycletime = 10
        basis_ds1.manage_addRRDDataPoint("basis1")

        basis_ds2 = PythonDataSource("basis2")
        template.datasources._setObject(basis_ds2.id, basis_ds2)
        basis_ds2 = template.datasources._getOb(basis_ds2.id)
        basis_ds2.cycletime = "${here/zCollectorClientTimeout}"
        basis_ds2.manage_addRRDDataPoint("basis2")

        # Calculated datasources.
        calc_ds1 = CalculatedPerformanceDataSource("calculated1")
        template.datasources._setObject(calc_ds1.id, calc_ds1)
        calc_ds1 = template.datasources._getOb(calc_ds1.id)
        calc_ds1.expression = "basis1 + basis2"
        calc_ds1.useBasisInterval = False
        calc_ds1.cycletime = 30
        calc_ds1.manage_addRRDDataPoint("calculated1")

        calc_ds2 = CalculatedPerformanceDataSource("calculated2")
        template.datasources._setObject(calc_ds2.id, calc_ds2)
        calc_ds2 = template.datasources._getOb(calc_ds2.id)
        calc_ds2.expression = "basis1 + basis2"
        calc_ds2.useBasisInterval = True
        calc_ds2.cycletime = 40
        calc_ds2.manage_addRRDDataPoint("calculated2")

        # Device
        device = deviceclass.createInstance("TestCalculatedPerformance")
        device.setPerformanceMonitor("localhost")

        # Santity checks.
        self.assertEqual(basis_ds1.cycletime, 10)
        self.assertEqual(basis_ds2.getCycleTime(device), 20)

        # useBasisInterval = False
        self.assertEqual(calc_ds1.getCycleTime(device), 30)

        # useBasisInterval = True
        self.assertEqual(calc_ds2.getCycleTime(device), 10)

        # minimumInterval
        calc_ds2.minimumInterval = None
        self.assertEqual(calc_ds2.getCycleTime(device), 10)
        calc_ds2.minimumInterval = 1
        self.assertEqual(calc_ds2.getCycleTime(device), 10)
        calc_ds2.minimumInterval = 20
        self.assertEqual(calc_ds2.getCycleTime(device), 20)
        calc_ds2.minimumInterval = None

        # maximumInterval
        calc_ds2.maximumInterval = None
        self.assertEqual(calc_ds2.getCycleTime(device), 10)
        calc_ds2.maximumInterval = 20
        self.assertEqual(calc_ds2.getCycleTime(device), 10)
        calc_ds2.maximumInterval = 1
        self.assertEqual(calc_ds2.getCycleTime(device), 1)
        calc_ds2.maximumInterval = None
