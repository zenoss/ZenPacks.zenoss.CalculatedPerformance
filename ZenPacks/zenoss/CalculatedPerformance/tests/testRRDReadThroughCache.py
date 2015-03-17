#
# Copyright (C) Zenoss, Inc. 2014, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
import Globals
import unittest
from mock import MagicMock, patch, DEFAULT
from Products.ZenTestCase.BaseTestCase import BaseTestCase
from ZenPacks.zenoss.CalculatedPerformance.ReadThroughCache import getReadThroughCache

def mockReturnValue(value):
    def inner(self, *args, **kwargs):
        return value
    return inner

class TestRRDReadThroughCache(BaseTestCase):

    def testPut(self):
        cache = getReadThroughCache()
        testKey = cache._getKey('ds', 'dp', 'rra', '1')
        cache.put('ds', 'dp', 'rra', '1', 42.0)
        cache._readLastValue = mockReturnValue(54.11)
        self.assertIn(testKey, cache._cache)
        self.assertEqual(cache.getLastValue('ds', 'dp', 'rra', "GAUGE", 1, {'rrdpath': 'perf/path', 'uuid': 1}), 42.0)

    def testGetLastValue(self):
        cache = getReadThroughCache()
        testKey = cache._getKey('ds', 'dp', 'rra', '1')
        cache._readLastValue = mockReturnValue(54.11)
        self.assertNotIn(testKey, cache._cache)
        self.assertEqual(cache.getLastValue('ds', 'dp', 'rra', "GAUGE", 1, {'rrdpath': 'perf/path', 'uuid': 1}), 54.11)
        self.assertIn(testKey, cache._cache)
        cache._readLastValue = mockReturnValue(65.43)
        self.assertEqual(cache.getLastValue('ds', 'dp', 'rra', "GAUGE", 1, {'rrdpath': 'perf/path', 'uuid': 1}), 54.11)

    def testGetLastValues(self):
        cache = getReadThroughCache()
        targets = [{'rrdpath': 'perf/path1', 'uuid': '1'},
                   {'rrdpath': 'perf/path2', 'uuid': '2'}]
        testKeys = [cache._getKey('ds', 'dp', 'rra', target['uuid']) for target in targets]
        cache._readLastValue = mockReturnValue(54.11)
        for testKey in testKeys:
            self.assertNotIn(testKey, cache._cache)
        self.assertDictEqual(cache.getLastValues('ds', 'dp', 'rra', "GAUGE", 1, targets)[0],
                                 {'1': 54.11, '2': 54.11})
        for testKey in testKeys:
            self.assertIn(testKey, cache._cache)
        cache._readLastValue = mockReturnValue(65.43)
        self.assertDictEqual(cache.getLastValues('ds', 'dp', 'rra', "GAUGE", 1, targets)[0],
                                 {'1': 54.11, '2': 54.11})
        cache._readLastValue = mockReturnValue(None)
        self.assertDictEqual(cache.getLastValues('ds', 'dp', 'rra', "GAUGE", 1, targets)[0],
                                 {'1': 54.11, '2': 54.11})

    def testInvalidate(self):
        cache = getReadThroughCache()

        testKey = cache._getKey('ds', 'dp', 'rra', '1')

        cache.put('ds', 'dp', 'rra', '1', 42.0)
        self.assertIn(testKey, cache._cache)
        cache.invalidate(testKey)
        self.assertNotIn(testKey, cache._cache)

        cache.put('ds', 'dp', 'rra', '1', 42.0)
        self.assertIn(testKey, cache._cache)
        cache.invalidate()
        self.assertNotIn(testKey, cache._cache)
        cache._readLastValue = mockReturnValue(54.11)
        self.assertEqual(cache.getLastValue('ds', 'dp', 'rra', "GAUGE", 1, {'rrdpath': 'perf/path', 'uuid': 1}), 54.11)
        self.assertIn(testKey, cache._cache)
        cache.invalidate(testKey)
        self.assertNotIn(testKey, cache._cache)

        self.assertEqual(cache.getLastValue('ds', 'dp', 'rra', "GAUGE", 1, {'rrdpath': 'perf/path', 'uuid': 1}), 54.11)
        self.assertIn(testKey, cache._cache)
        cache.invalidate()
        self.assertNotIn(testKey, cache._cache)


def test_suite():
    from unittest import TestSuite, makeSuite
    suite = TestSuite()
    suite.addTest(makeSuite(TestRRDReadThroughCache))
    return suite

if __name__ == '__main__':
    unittest.main(defaultTest='test_suite')
