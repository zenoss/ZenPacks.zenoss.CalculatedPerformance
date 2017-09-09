##############################################################################
#
# Copyright (C) Zenoss, Inc. 2017, all rights reserved.
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
        deviceclass = self.dmd.Devices.createOrganizer("/Test/CalculatedPerformance")
        deviceclass.setZenProperty("zCollectorClientTimeout", 20)

        deviceclass.manage_addRRDTemplate("Device")
        template = deviceclass.rrdTemplates._getOb("Device")

        # Basis datasources.
        basis_datasource1 = BasicDataSource("basis1")
        template.datasources._setObject(basis_datasource1.id, basis_datasource1)
        basis_datasource1 = template.datasources._getOb(basis_datasource1.id)
        basis_datasource1.sourcetype = "COMMAND"
        basis_datasource1.cycletime = 10
        basis_datasource1.manage_addRRDDataPoint("basis1")

        basis_datasource2 = PythonDataSource("basis2")
        template.datasources._setObject(basis_datasource2.id, basis_datasource2)
        basis_datasource2 = template.datasources._getOb(basis_datasource2.id)
        basis_datasource2.cycletime = "${here/zCollectorClientTimeout}"
        basis_datasource2.manage_addRRDDataPoint("basis2")

        # Calculated datasources.
        calculated_datasource1 = CalculatedPerformanceDataSource("calculated1")
        template.datasources._setObject(calculated_datasource1.id, calculated_datasource1)
        calculated_datasource1 = template.datasources._getOb(calculated_datasource1.id)
        calculated_datasource1.expression = "basis1 + basis2"
        calculated_datasource1.useBasisInterval = False
        calculated_datasource1.cycletime = 30
        calculated_datasource1.manage_addRRDDataPoint("calculated1")

        calculated_datasource2 = CalculatedPerformanceDataSource("calculated2")
        template.datasources._setObject(calculated_datasource2.id, calculated_datasource2)
        calculated_datasource2 = template.datasources._getOb(calculated_datasource2.id)
        calculated_datasource2.expression = "basis1 + basis2"
        calculated_datasource2.useBasisInterval = True
        calculated_datasource2.cycletime = 40
        calculated_datasource2.manage_addRRDDataPoint("calculated2")

        # Device
        device = deviceclass.createInstance("TestCalculatedPerformance")
        device.setPerformanceMonitor("localhost")

        # Santity checks.
        self.assertEqual(basis_datasource1.cycletime, 10)
        self.assertEqual(basis_datasource2.getCycleTime(device), 20)

        # useBasisInterval = False
        self.assertEqual(calculated_datasource1.getCycleTime(device), 30)

        # useBasisInterval = True
        self.assertEqual(calculated_datasource2.getCycleTime(device), 10)

        # minimumInterval
        calculated_datasource2.minimumInterval = None
        self.assertEqual(calculated_datasource2.getCycleTime(device), 10)
        calculated_datasource2.minimumInterval = 1
        self.assertEqual(calculated_datasource2.getCycleTime(device), 10)
        calculated_datasource2.minimumInterval = 20
        self.assertEqual(calculated_datasource2.getCycleTime(device), 20)
        calculated_datasource2.minimumInterval = None

        # maximumInterval
        calculated_datasource2.maximumInterval = None
        self.assertEqual(calculated_datasource2.getCycleTime(device), 10)
        calculated_datasource2.maximumInterval = 20
        self.assertEqual(calculated_datasource2.getCycleTime(device), 10)
        calculated_datasource2.maximumInterval = 1
        self.assertEqual(calculated_datasource2.getCycleTime(device), 1)
        calculated_datasource2.maximumInterval = None
