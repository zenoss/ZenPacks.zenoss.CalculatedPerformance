##############################################################################
#
# Copyright (C) Zenoss, Inc. 2014, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################
import unittest

from Products.ZenTestCase.BaseTestCase import BaseTestCase
from ZenPacks.zenoss.CalculatedPerformance.utils import *


class TestUtils(BaseTestCase):
    def testTopoSort(self):
        d1 = {
            2: {11},
            9: {11, 8},
            10: {11, 3},
            11: {7, 5},
            8: {7, 3},
            3: set(),
            5: set(),
            7: set(),
        }
        self.assertEqual(list(toposort(d1)), [3, 5, 7, 8, 11, 9, 2, 10])

    def testGetTargetId(self):
        self.assertEqual(getTargetId({}), '_')
        self.assertEqual(getTargetId({'device': {}}), '_')
        self.assertEqual(getTargetId({'id': 'test'}), 'test_')
        self.assertEqual(getTargetId({'id': 'testc', 'device': {}}), '_testc')
        self.assertEqual(getTargetId({'id': 'testc', 'device': {'id': 'test'}}), 'test_testc')

    def _getSimpleObject(self, attrs={}):
        obj = SimpleObject()
        for k,v in attrs.items():
            setattr(obj, k, v)
        return obj

    def _getTestObj(self):
        testObj = SimpleObject()
        testObj.str1 = 'str1'
        testObj.int2 = 2
        testObj.float3 = 3.003
        testObj.strfunc4 = lambda: "func4"
        testObj.intfunc5 = lambda: 5
        testObj.floatfunc6 = lambda: 6.006
        testObj.subobj7 = SimpleObject()
        testObj.subobj7.str10 = 'str10'
        testObj.subobj7.int20 = 20
        testObj.subobj7.float30 = 30.003
        testObj.subobj7.strfunc40 = lambda: "func40"
        testObj.subobj7.intfunc50 = lambda: 50
        testObj.subobj7.floatfunc60 = lambda: 60.006
        testObj.subobj7.objfuncSelf = lambda: testObj
        testObj.objfunc8 = lambda: testObj.subobj7
        testObj.chainfunc9 = lambda: [
            self._getSimpleObject({'subchain': [1,2,3]}),
            self._getSimpleObject({'subchain': 4}),
            self._getSimpleObject({'subchain': [5,6]}),
            self._getSimpleObject({'subchain': 7}),
        ]
        testObj.chainfunc10 = lambda: [
            self._getSimpleObject({'subchain': lambda: [1,2,3]}),
            self._getSimpleObject({'subchain': lambda: 4}),
            self._getSimpleObject({'subchain': lambda: [5,6]}),
            self._getSimpleObject({'subchain': lambda: 7}),
        ]
        return testObj

    def testDotTraverseInvalidCases(self):
        self.assertEqual(dotTraverse(None, ''), None)
        self.assertEqual(dotTraverse(None, 'here'), None)
        self.assertEqual(dotTraverse(None, None), None)

        testObj = SimpleObject()

        self.assertEqual(dotTraverse(testObj, ''), None)
        self.assertEqual(dotTraverse(testObj, 'here'), testObj)
        self.assertEqual(dotTraverse(testObj, None), None)
        self.assertEqual(dotTraverse(testObj, 'invalid'), None)
        self.assertEqual(dotTraverse(testObj, 'here.invalid'), None)
        self.assertEqual(dotTraverse(testObj, 'str1'), None)
        self.assertEqual(dotTraverse(testObj, 'here.str1'), None)
        self.assertEqual(dotTraverse(testObj, 'int2'), None)
        self.assertEqual(dotTraverse(testObj, 'here.int2'), None)
        self.assertEqual(dotTraverse(testObj, 'float3'), None)
        self.assertEqual(dotTraverse(testObj, 'here.float3'), None)

        testObj = self._getTestObj()

        self.assertEqual(dotTraverse(testObj, ''), None)
        self.assertEqual(dotTraverse(testObj, 'here'), testObj)
        self.assertEqual(dotTraverse(testObj, None), None)
        self.assertEqual(dotTraverse(testObj, 'invalid'), None)
        self.assertEqual(dotTraverse(testObj, 'here.invalid'), None)
        self.assertEqual(dotTraverse(testObj, 'subobj7.'), None)
        self.assertEqual(dotTraverse(testObj, 'here.subobj7.'), None)
        self.assertEqual(dotTraverse(testObj, 'subobj7..'), None)
        self.assertEqual(dotTraverse(testObj, 'here.subobj7..'), None)
        self.assertEqual(dotTraverse(testObj, 'subobj7.invalid'), None)
        self.assertEqual(dotTraverse(testObj, 'here.subobj7.invalid'), None)

    def testDotTraverseAttributes(self):
        testObj = self._getTestObj()
        self.assertEqual(dotTraverse(testObj, 'str1'), testObj.str1)
        self.assertEqual(dotTraverse(testObj, 'here.str1'), testObj.str1)
        self.assertEqual(dotTraverse(testObj, 'int2'), testObj.int2)
        self.assertEqual(dotTraverse(testObj, 'here.int2'), testObj.int2)
        self.assertEqual(dotTraverse(testObj, 'float3'), testObj.float3)
        self.assertEqual(dotTraverse(testObj, 'here.float3'), testObj.float3)

    def testDotTraverseCallableAttributes(self):
        testObj = self._getTestObj()
        self.assertEqual(dotTraverse(testObj, 'strfunc4'), testObj.strfunc4())
        self.assertEqual(dotTraverse(testObj, 'here.strfunc4'), testObj.strfunc4())
        self.assertEqual(dotTraverse(testObj, 'intfunc5'), testObj.intfunc5())
        self.assertEqual(dotTraverse(testObj, 'here.intfunc5'), testObj.intfunc5())
        self.assertEqual(dotTraverse(testObj, 'floatfunc6'), testObj.floatfunc6())
        self.assertEqual(dotTraverse(testObj, 'here.floatfunc6'), testObj.floatfunc6())

    def testDotTraverseSubObjectAttributes(self):
        testObj = self._getTestObj()
        self.assertEqual(dotTraverse(testObj, 'subobj7'), testObj.subobj7)
        self.assertEqual(dotTraverse(testObj, 'here.subobj7'), testObj.subobj7)
        self.assertEqual(dotTraverse(testObj, 'subobj7.'), None)
        self.assertEqual(dotTraverse(testObj, 'here.subobj7.'), None)
        self.assertEqual(dotTraverse(testObj, 'subobj7.invalid'), None)
        self.assertEqual(dotTraverse(testObj, 'here.subobj7.invalid'), None)
        self.assertEqual(dotTraverse(testObj, 'subobj7.str10'), testObj.subobj7.str10)
        self.assertEqual(dotTraverse(testObj, 'here.subobj7.str10'), testObj.subobj7.str10)
        self.assertEqual(dotTraverse(testObj, 'subobj7.int20'), testObj.subobj7.int20)
        self.assertEqual(dotTraverse(testObj, 'here.subobj7.int20'), testObj.subobj7.int20)
        self.assertEqual(dotTraverse(testObj, 'subobj7.float30'), testObj.subobj7.float30)
        self.assertEqual(dotTraverse(testObj, 'here.subobj7.float30'), testObj.subobj7.float30)

    def testDotTraverseSubObjectCallableAttributes(self):
        testObj = self._getTestObj()
        self.assertEqual(dotTraverse(testObj, 'subobj7.strfunc40'), testObj.subobj7.strfunc40())
        self.assertEqual(dotTraverse(testObj, 'here.subobj7.strfunc40'), testObj.subobj7.strfunc40())
        self.assertEqual(dotTraverse(testObj, 'subobj7.intfunc50'), testObj.subobj7.intfunc50())
        self.assertEqual(dotTraverse(testObj, 'here.subobj7.intfunc50'), testObj.subobj7.intfunc50())
        self.assertEqual(dotTraverse(testObj, 'subobj7.floatfunc60'), testObj.subobj7.floatfunc60())
        self.assertEqual(dotTraverse(testObj, 'here.subobj7.floatfunc60'), testObj.subobj7.floatfunc60())
        self.assertEqual(dotTraverse(testObj, 'subobj7.objfuncSelf'), testObj)
        self.assertEqual(dotTraverse(testObj, 'here.subobj7.objfuncSelf'), testObj)
        self.assertEqual(dotTraverse(testObj, 'subobj7.objfuncSelf.subobj7.objfuncSelf'), testObj)
        self.assertEqual(dotTraverse(testObj, 'here.subobj7.objfuncSelf.subobj7.objfuncSelf'), testObj)
        self.assertEqual(dotTraverse(testObj, 'subobj7.objfuncSelf.subobj7.objfuncSelf.subobj7.objfuncSelf'), testObj)
        self.assertEqual(dotTraverse(testObj, 'here.subobj7.objfuncSelf.subobj7.objfuncSelf.subobj7.objfuncSelf'), testObj)

    def testDotTraverseCallableSubObjectAttributes(self):
        testObj = self._getTestObj()
        self.assertEqual(dotTraverse(testObj, 'objfunc8.str10'), testObj.subobj7.str10)
        self.assertEqual(dotTraverse(testObj, 'here.objfunc8.str10'), testObj.subobj7.str10)
        self.assertEqual(dotTraverse(testObj, 'objfunc8.int20'), testObj.subobj7.int20)
        self.assertEqual(dotTraverse(testObj, 'here.objfunc8.int20'), testObj.subobj7.int20)
        self.assertEqual(dotTraverse(testObj, 'objfunc8.float30'), testObj.subobj7.float30)
        self.assertEqual(dotTraverse(testObj, 'here.objfunc8.float30'), testObj.subobj7.float30)

    def testDotTraverseCallableSubObjectCallableAttributes(self):
        testObj = self._getTestObj()
        self.assertEqual(dotTraverse(testObj, 'objfunc8.strfunc40'), testObj.subobj7.strfunc40())
        self.assertEqual(dotTraverse(testObj, 'here.objfunc8.strfunc40'), testObj.subobj7.strfunc40())
        self.assertEqual(dotTraverse(testObj, 'objfunc8.intfunc50'), testObj.subobj7.intfunc50())
        self.assertEqual(dotTraverse(testObj, 'here.objfunc8.intfunc50'), testObj.subobj7.intfunc50())
        self.assertEqual(dotTraverse(testObj, 'objfunc8.floatfunc60'), testObj.subobj7.floatfunc60())
        self.assertEqual(dotTraverse(testObj, 'here.objfunc8.floatfunc60'), testObj.subobj7.floatfunc60())
        self.assertEqual(dotTraverse(testObj, 'objfunc8.objfuncSelf'), testObj)
        self.assertEqual(dotTraverse(testObj, 'here.objfunc8.objfuncSelf'), testObj)
        self.assertEqual(dotTraverse(testObj, 'objfunc8.objfuncSelf.objfunc8.objfuncSelf'), testObj)
        self.assertEqual(dotTraverse(testObj, 'here.objfunc8.objfuncSelf.objfunc8.objfuncSelf'), testObj)
        self.assertEqual(dotTraverse(testObj, 'objfunc8.objfuncSelf.objfunc8.objfuncSelf.objfunc8.objfuncSelf'), testObj)
        self.assertEqual(dotTraverse(testObj, 'here.objfunc8.objfuncSelf.objfunc8.objfuncSelf.objfunc8.objfuncSelf'), testObj)

    def testDotTraverseCallableChain(self):
        testObj = self._getTestObj()
        self.assertEqual(dotTraverse(testObj, 'chainfunc9.subchain'), [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(dotTraverse(testObj, 'here.chainfunc9.subchain'), [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(dotTraverse(testObj, 'chainfunc10.subchain'), [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(dotTraverse(testObj, 'here.chainfunc10.subchain'), [1, 2, 3, 4, 5, 6, 7])


def test_suite():
    from unittest import TestSuite, makeSuite
    suite = TestSuite()
    suite.addTest(makeSuite(TestUtils))
    return suite

if __name__ == '__main__':
    unittest.main(defaultTest='test_suite')
