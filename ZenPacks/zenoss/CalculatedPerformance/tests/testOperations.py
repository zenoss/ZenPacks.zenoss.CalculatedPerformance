##############################################################################
#
# Copyright (C) Zenoss, Inc. 2014, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################
import unittest
from uuid import uuid4

from Products.ZenTestCase.BaseTestCase import BaseTestCase
from ZenPacks.zenoss.CalculatedPerformance.operations import *
from ZenPacks.zenoss.CalculatedPerformance.operations import _amean, _median, \
    _deviations, _absoluteDeviations, _nthPercentileRank


def _constructValueMap(values):
    return dict(zip((uuid4() for x in values), values))


class TestOperations(BaseTestCase):
    def testMean(self):
        self.assertEqual(_amean([0, 1, 2, 3, 4, 5, 6, 7, 8, 9]), 4.5)
        self.assertEqual(_amean([1, 2]), 1.5)
        self.assertEqual(_amean([]), None)
        self.assertEqual(_amean([45]), 45)

    def testMedian(self):
        self.assertEqual(_median([0, 1, 2, 3, 4, 5, 6, 7, 8, 9]), 4.5)
        self.assertEqual(_median([0, 1, 2, 3, 4, 5, 6, 7, 8]), 4)
        self.assertEqual(_median([1, 2, 3, 4, 5, 6, 7, 8, 9]), 5)
        self.assertEqual(_median([1, 2]), 1.5)
        self.assertEqual(_median([]), None)
        self.assertEqual(_median([45]), 45)
        self.assertEqual(_median([1, 1, 2, 2, 4, 6, 9]), 2)

    def testSum(self):
        self.assertEqual(sum(_constructValueMap([0, 1, 2, 3, 4, 5, 6, 7, 8, 9]))[0], 45)
        self.assertEqual(sum(_constructValueMap([0, 1, 2, 3, 4, 5, 6, 7, 8]))[0], 36)
        self.assertEqual(sum(_constructValueMap([1, 2, 3, 4, 5, 6, 7, 8, 9]))[0], 45)
        self.assertEqual(sum(_constructValueMap([1, 2]))[0], 3)
        self.assertEqual(sum(_constructValueMap([45]))[0], 45)

    def testMax(self):
        self.assertEqual(max(_constructValueMap([0, 1, 2, 3, 4, 5, 6, 7, 8, 9]))[0], 9)
        self.assertEqual(max(_constructValueMap([0, 1, 2, 3, 4, 5, 6, 7, 8]))[0], 8)
        self.assertEqual(max(_constructValueMap([1, 2, 3, 4, 5, 6, 7, 8, 9]))[0], 9)
        self.assertEqual(max(_constructValueMap([1, 2]))[0], 2)
        self.assertEqual(max(_constructValueMap([45]))[0], 45)

    def testMin(self):
        self.assertEqual(min(_constructValueMap([0, 1, 2, 3, 4, 5, 6, 7, 8, 9]))[0], 0)
        self.assertEqual(min(_constructValueMap([0, 1, 2, 3, 4, 5, 6, 7, 8]))[0], 0)
        self.assertEqual(min(_constructValueMap([1, 2, 3, 4, 5, 6, 7, 8, 9]))[0], 1)
        self.assertEqual(min(_constructValueMap([1, 2]))[0], 1)
        self.assertEqual(min(_constructValueMap([45]))[0], 45)

    def testAmean(self):
        self.assertEqual(amean(_constructValueMap([0, 1, 2, 3, 4, 5, 6, 7, 8, 9]))[0], 4.5)
        self.assertEqual(amean(_constructValueMap([0, 1, 2, 3, 4, 5, 6, 7, 8]))[0], 4)
        self.assertEqual(amean(_constructValueMap([1, 2, 3, 4, 5, 6, 7, 8, 9]))[0], 5)
        self.assertEqual(amean(_constructValueMap([1, 2]))[0], 1.5)
        self.assertEqual(amean(_constructValueMap([45]))[0], 45)

        self.assertEqual(avg(_constructValueMap([0, 1, 2, 3, 4, 5, 6, 7, 8, 9]))[0], 4.5)
        self.assertEqual(avg(_constructValueMap([0, 1, 2, 3, 4, 5, 6, 7, 8]))[0], 4)
        self.assertEqual(avg(_constructValueMap([1, 2, 3, 4, 5, 6, 7, 8, 9]))[0], 5)
        self.assertEqual(avg(_constructValueMap([1, 2]))[0], 1.5)
        self.assertEqual(avg(_constructValueMap([45]))[0], 45)

    def testDeviations(self):
        self.assertEqual(_deviations(_amean, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]),
                         [-4.5, -3.5, -2.5, -1.5, -0.5, 0.5, 1.5, 2.5, 3.5, 4.5])
        self.assertEqual(_deviations(_amean, [0, 1, 2, 3, 4, 5, 6, 7, 8]),
                         [-4, -3, -2, -1, 0, 1, 2, 3, 4])
        self.assertEqual(_deviations(_amean, [1, 2, 3, 4, 5, 6, 7, 8, 9]),
                         [-4, -3, -2, -1, 0, 1, 2, 3, 4])
        self.assertEqual(_deviations(_amean, [1, 2]), [-0.5, 0.5])
        self.assertEqual(_deviations(_amean, []), [])
        self.assertEqual(_deviations(_amean, [45]), [0])

    def testAbsoluteDeviations(self):
        self.assertEqual(_absoluteDeviations(_amean, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]),
                         [4.5, 3.5, 2.5, 1.5, 0.5, 0.5, 1.5, 2.5, 3.5, 4.5])
        self.assertEqual(_absoluteDeviations(_amean, [0, 1, 2, 3, 4, 5, 6, 7, 8]),
                         [4, 3, 2, 1, 0, 1, 2, 3, 4])
        self.assertEqual(_absoluteDeviations(_amean, [1, 2, 3, 4, 5, 6, 7, 8, 9]),
                         [4, 3, 2, 1, 0, 1, 2, 3, 4])
        self.assertEqual(_absoluteDeviations(_amean, [1, 2]), [0.5, 0.5])
        self.assertEqual(_absoluteDeviations(_amean, []), [])
        self.assertEqual(_absoluteDeviations(_amean, [45]), [0])
        self.assertEqual(_absoluteDeviations(_median, [1, 1, 2, 2, 4, 6, 9]),
                         [1, 1, 0, 0, 2, 4, 7])

    def testStd(self):
        self.assertEqual(std(_constructValueMap([2, 4, 4, 4, 5, 5, 7, 9]))[0], 2)
        self.assertEqual(stddev(_constructValueMap([2, 4, 4, 4, 5, 5, 7, 9]))[0], 2)

    def testVar(self):
        self.assertEqual(var(_constructValueMap([2, 4, 4, 4, 5, 5, 7, 9]))[0], 4)

    def testMad(self):
        self.assertEqual(mad(_constructValueMap([1, 1, 2, 2, 4, 6, 9]))[0], 1)

    def testnthPercentile(self):
        # basic integer numeric stability
        for i in range(100):
            val = _nthPercentileRank(i, 100)
            self.assertEqual(val, i,
                             msg="%sth percentile of 100 values is not %s: %s" % (i, i, val))

        # a bit fuzzier check for floating point values converted from [0,1] range
        for i in range(101):
            n = 0.01 * i
            val = _nthPercentileRank(n * 100, 101)
            variance = abs(val-i)
            self.assertTrue(variance <= 1,
                            msg="Variance between calculated %s and provided %s exceeds 1: %s" %
                                (val, i, variance))

        self.assertRaises(ValueError, _nthPercentileRank, -1, 0)
        self.assertRaises(ValueError, _nthPercentileRank, 101, 0)

def test_suite():
    from unittest import TestSuite, makeSuite
    suite = TestSuite()
    suite.addTest(makeSuite(TestOperations))
    return suite

if __name__ == '__main__':
    unittest.main(defaultTest='test_suite')
