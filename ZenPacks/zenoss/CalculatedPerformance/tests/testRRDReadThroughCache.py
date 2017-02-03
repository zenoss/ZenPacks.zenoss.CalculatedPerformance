#
# Copyright (C) Zenoss, Inc. 2014-2017, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#

import Globals

import unittest
import time

from collections import deque

from Products.ZenTestCase.BaseTestCase import BaseTestCase

from ZenPacks.zenoss.CalculatedPerformance.ReadThroughCache import getReadThroughCache


def mockReturnValue(value):
    def inner(self, *args, **kwargs):
        return value
    return inner


class TestRRDReadThroughCache(BaseTestCase):

    def _getKey(self, ds, dp, rra, rrdpath, uuid):
        """Return correct cache key for cache implementation."""
        cache = getReadThroughCache()
        self.assertIn(cache._targetKey, ('rrdpath', 'uuid'))
        if cache._targetKey == 'uuid':
            return cache._getKey(ds, dp, rra, uuid)
        elif cache._targetKey == 'rrdpath':
            return cache._getKey(ds, dp, rra, rrdpath)

    def testPut(self):
        cache = getReadThroughCache()
        testKey = self._getKey('ds', 'dp', 'rra', 'perf/path', '1')
        cache.put('ds', 'dp', 'rra', 'perf/path', '1', 42.0)
        cache._readLastValue = mockReturnValue(54.11)
        self.assertIn(testKey, cache._cache)
        self.assertEqual(
            cache.getLastValue(
                'ds', 'dp', 'rra', False, 1, {'rrdpath': 'perf/path', 'uuid': 1})[0],
            42.0)

    def testGetLastValue(self):
        cache = getReadThroughCache()
        testKey = self._getKey('ds', 'dp', 'rra', 'perf/path', '1')
        cache._readLastValue = mockReturnValue(54.11)
        self.assertNotIn(testKey, cache._cache)
        self.assertEqual(
            cache.getLastValue(
                'ds', 'dp', 'rra', False, 1, {'rrdpath': 'perf/path', 'uuid': 1})[0][0], 
            54.11)
        self.assertIn(testKey, cache._cache)
        cache._readLastValue = mockReturnValue(65.43)
        self.assertEqual(
            cache.getLastValue(
                'ds', 'dp', 'rra', False, 1, {'rrdpath': 'perf/path', 'uuid': 1})[0][0], 
            54.11)

    def testGetLastValues(self):
        cache = getReadThroughCache()
        targets = [{'rrdpath': 'perf/path1', 'uuid': '1'},
                   {'rrdpath': 'perf/path2', 'uuid': '2'}]
        testKeys = [
            self._getKey('ds', 'dp', 'rra', target['rrdpath'], target['uuid'])
            for target in targets]

        cache._readLastValue = mockReturnValue(54.11)
        for testKey in testKeys:
            self.assertNotIn(testKey, cache._cache)

        expectedValues = cache.getLastValues('ds', 'dp', 'rra', False, 1, targets)[0]
        self.assertDictEqual(
            {k,v[0][0] for k,v in expectedValues.itervalues(),}
            {'1': 54.11, '2': 54.11})

        for testKey in testKeys:
            self.assertIn(testKey, cache._cache)

        cache._readLastValue = mockReturnValue(65.43)
        expectedValues = cache.getLastValues('ds', 'dp', 'rra', False, 1, targets)[0]
        self.assertDictEqual(
            {k,v[0][0] for k,v in expectedValues.itervalues(),}
            {'1': 54.11, '2': 54.11})

        cache._readLastValue = mockReturnValue(None)
        expectedValues = cache.getLastValues('ds', 'dp', 'rra', False, 1, targets)[0]
        self.assertDictEqual(
            {k,v[0][0] for k,v in expectedValues.itervalues(),}
            {'1': 54.11, '2': 54.11})

    def testInvalidate(self):
        cache = getReadThroughCache()

        testKey = self._getKey('ds', 'dp', 'rra', 'perf/path', '1')

        cache.put('ds', 'dp', 'rra', 'perf/path', '1', 42.0)
        self.assertIn(testKey, cache._cache)
        cache.invalidate(testKey)
        self.assertNotIn(testKey, cache._cache)

        cache.put('ds', 'dp', 'rra', 'perf/path', '1', 42.0)
        self.assertIn(testKey, cache._cache)
        cache.invalidate()
        self.assertNotIn(testKey, cache._cache)
        cache._readLastValue = mockReturnValue(54.11)
        self.assertEqual(
            cache.getLastValue(
                'ds', 'dp', 'rra', False, 1, {'rrdpath': 'perf/path', 'uuid': 1})[0][0], 
            54.11)
        self.assertIn(testKey, cache._cache)
        cache.invalidate(testKey)
        self.assertNotIn(testKey, cache._cache)

        self.assertEqual(
            cache.getLastValue(
                'ds', 'dp', 'rra', False, 1, {'rrdpath': 'perf/path', 'uuid': 1})[0][0],
            54.11)
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
