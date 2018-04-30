##############################################################################
#
# Copyright (C) Zenoss, Inc. 2015-2018, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

"""Tests for DynamicView adapters."""

# stdlib Imports
import collections
import unittest

# Zenoss Imports
from Products.Five import zcml
from Products.ZenTestCase.BaseTestCase import BaseTestCase

# DynamicView Imports
try:
    from ZenPacks.zenoss.DynamicView import TAG_IMPACTED_BY, TAG_IMPACTS
    from ZenPacks.zenoss.DynamicView.interfaces import IRelatable

    DYNAMICVIEW_INSTALLED = True
except ImportError:
    TAG_IMPACTED_BY, TAG_IMPACTS = None, None

    DYNAMICVIEW_INSTALLED = False


RelationTuple = collections.namedtuple(
    'RelationTuple',
    ['source', 'tag', 'target'])


def relation_tuples_for(obj, tags=None):
    """Return set of RelationTuple instances."""
    if not tags:
        tags = (TAG_IMPACTED_BY, TAG_IMPACTS)

    relation_tuples = set()
    relatable = IRelatable(obj)

    for tag in tags:
        for relation in relatable.relations(type=tag):
            for tag in relation.tags:
                relation_tuples.add(
                    RelationTuple(
                        source=relation.source.id.split('/')[-1],
                        tag=tag,
                        target=relation.target.id.split('/')[-1]))

    return frozenset(relation_tuples)


@unittest.skipUnless(DYNAMICVIEW_INSTALLED, "DynamicView not installed")
class TestDynamicView(BaseTestCase):
    """Test suite for DynamicView adapters."""

    def afterSetUp(self):
        super(TestDynamicView, self).afterSetUp()

        # Load DynamicView ZCML.
        try:
            import ZenPacks.zenoss.DynamicView
            zcml.load_config('configure.zcml', ZenPacks.zenoss.DynamicView)
        except ImportError:
            pass

        # Load our own ZCML.
        import ZenPacks.zenoss.CalculatedPerformance
        zcml.load_config(
            'configure.zcml', ZenPacks.zenoss.CalculatedPerformance)

    def assertExactRelations(self, obj, expected):
        """Assert that obj has expected relations and no more."""
        expected_relations = set()

        for tag, targets in expected.items():
            for target in targets:
                expected_relations.add(
                    RelationTuple(source=obj.id, tag=tag, target=target))

        relations = relation_tuples_for(obj)

        missing_relations = expected_relations.difference(relations)
        self.assertFalse(
            missing_relations,
            'missing relations: {}'.format(missing_relations))

        extra_relations = relations.difference(expected_relations)
        self.assertFalse(
            extra_relations,
            'extra relations: {}'.format(extra_relations))

    @unittest.skip("relationships known to be inconsistent")
    def test_dv_consistent(self):
        relation_tuples = set()
        relation_tuples.update(relation_tuples_for(self.device))

        for component in self.device.getDeviceComponents():
            relation_tuples.update(relation_tuples_for(component))

        reverse_tuples = set()

        for relation_tuple in relation_tuples:
            reverse_tag = {
                TAG_IMPACTS: TAG_IMPACTED_BY,
                TAG_IMPACTED_BY: TAG_IMPACTS,
                }.get(relation_tuple.tag)

            if not reverse_tag:
                continue

            reverse_tuples.add(
                RelationTuple(
                    source=relation_tuple.target,
                    tag=reverse_tag,
                    target=relation_tuple.source))

        missing_reverses = relation_tuples.difference(reverse_tuples)
        self.assertFalse(
            missing_reverses,
            'missing reverses: {}'.format(missing_reverses))

    def test_dv_ElementPool(self):
        device = self.dmd.Devices.createInstance('test-device')

        from Products.ZenModel.IpInterface import IpInterface
        eth0 = IpInterface('eth0')
        device.os.interfaces._setObject(eth0.id, eth0)
        eth0 = device.os.interfaces._getOb(eth0.id)

        from Products.ZenUtils.guid.interfaces import IGlobalIdentifier
        eth0_guid = IGlobalIdentifier(eth0).getGUID()

        from ZenPacks.zenoss.CalculatedPerformance.ElementPool \
            import ElementPool
        pool0 = ElementPool('pool0')
        device.aggregatingPools._setObject(pool0.id, pool0)
        pool0 = device.aggregatingPools._getOb(pool0.id)
        pool0.members.add(eth0_guid)

        self.assertExactRelations(
            pool0, {
                TAG_IMPACTED_BY: ['eth0'],
            })
