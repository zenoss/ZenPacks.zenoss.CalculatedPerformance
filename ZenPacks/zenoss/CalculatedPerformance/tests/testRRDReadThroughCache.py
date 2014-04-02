# 
# Copyright (C) Zenoss, Inc. 2014, all rights reserved.
# 
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
# 

import unittest
from mock import MagicMock, patch, DEFAULT
from Products.ZenTestCase.BaseTestCase import BaseTestCase
from ZenPacks.zenoss.CalculatedPerformance.RRDReadThroughCache import RRDReadThroughCache


class TestRRDReadThroughCache(BaseTestCase):

    def testPut(self):
        cache = RRDReadThroughCache()
        testKey = cache.getKey('ds', 'dp', 'rra', 'perf/path')
        cache.put('ds', 'dp', 'rra', 'perf/path', 42.0)
        with patch('ZenPacks.zenoss.CalculatedPerformance.RRDReadThroughCache.RRDReadThroughCache._readLastValue') \
            as _readLastValue:
            _readLastValue.return_value = 54.11
            self.assertIn(testKey, cache._cache)
            self.assertEqual(cache.getLastValue('ds', 'dp', 'rra', 1, {'rrdpath': 'perf/path'}), 42.0)

    def testGetLastValue(self):
        cache = RRDReadThroughCache()
        testKey = cache.getKey('ds', 'dp', 'rra', 'perf/path')
        with patch('ZenPacks.zenoss.CalculatedPerformance.RRDReadThroughCache.RRDReadThroughCache._readLastValue') \
            as _readLastValue:
            _readLastValue.return_value = 54.11
            self.assertNotIn(testKey, cache._cache)
            self.assertEqual(cache.getLastValue('ds', 'dp', 'rra', 1, {'rrdpath': 'perf/path'}), 54.11)
            self.assertIn(testKey, cache._cache)
            _readLastValue.return_value = 65.43
            self.assertEqual(cache.getLastValue('ds', 'dp', 'rra', 1, {'rrdpath': 'perf/path'}), 54.11)

    def testGetLastValues(self):
        cache = RRDReadThroughCache()
        targets = [{'rrdpath': 'perf/path1', 'uuid': '1'},
                   {'rrdpath': 'perf/path2', 'uuid': '2'}]
        testKeys = [cache.getKey('ds', 'dp', 'rra', target['rrdpath']) for target in targets]

        with patch('ZenPacks.zenoss.CalculatedPerformance.RRDReadThroughCache.RRDReadThroughCache._readLastValue') \
            as _readLastValue:
            _readLastValue.return_value = 54.11
            for testKey in testKeys:
                self.assertNotIn(testKey, cache._cache)
            self.assertDictEqual(cache.getLastValues('ds', 'dp', 'rra', 1, targets),
                                 {'1': 54.11, '2': 54.11})
            for testKey in testKeys:
                self.assertIn(testKey, cache._cache)
            _readLastValue.return_value = 65.43
            self.assertDictEqual(cache.getLastValues('ds', 'dp', 'rra', 1, targets),
                                 {'1': 54.11, '2': 54.11})
            _readLastValue.return_value = None
            self.assertDictEqual(cache.getLastValues('ds', 'dp', 'rra', 1, targets),
                                 {'1': 54.11, '2': 54.11})

    def testInvalidate(self):
        cache = RRDReadThroughCache()
        testKey = cache.getKey('ds', 'dp', 'rra', 'perf/path')

        cache.put('ds', 'dp', 'rra', 'perf/path', 42.0)
        self.assertIn(testKey, cache._cache)
        cache.invalidate(testKey)
        self.assertNotIn(testKey, cache._cache)

        cache.put('ds', 'dp', 'rra', 'perf/path', 42.0)
        self.assertIn(testKey, cache._cache)
        cache.invalidate()
        self.assertNotIn(testKey, cache._cache)

        with patch('ZenPacks.zenoss.CalculatedPerformance.RRDReadThroughCache.RRDReadThroughCache._readLastValue') \
            as _readLastValue:
            _readLastValue.return_value = 54.11
            self.assertEqual(cache.getLastValue('ds', 'dp', 'rra', 1, {'rrdpath': 'perf/path'}), 54.11)
            self.assertIn(testKey, cache._cache)
            cache.invalidate(testKey)
            self.assertNotIn(testKey, cache._cache)

            self.assertEqual(cache.getLastValue('ds', 'dp', 'rra', 1, {'rrdpath': 'perf/path'}), 54.11)
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
