##############################################################################
#
# Copyright (C) Zenoss, Inc. 2015-2018, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

"""DynamicView adapters for CalculatedPerformance.

This module depends on DynamicView implicitly and assumes it won't be imported
unless DynamicView is installed. This is accomplished by being registered in a
conditional ZCML section in configure.zcml.

"""

import logging

from zope.component import adapts
from zope.interface import implements

from ZenPacks.zenoss.DynamicView import TAG_ALL, TAG_IMPACTED_BY
from ZenPacks.zenoss.DynamicView.interfaces import IRelationsProvider
from ZenPacks.zenoss.DynamicView.model.adapters import BaseRelationsProvider

from .ElementPool import ElementPool


LOG = logging.getLogger('zen.CalculatedPerformance')


class ElementPoolRelationsProvider(BaseRelationsProvider):
    """DynamicView IRelationsProvider adaptor factory for ElementPool."""

    implements(IRelationsProvider)
    adapts(ElementPool)

    def relations(self, type=TAG_ALL):
        """Generate IRelation instances.

        One (pool <- impacted_by <- member) IRelation for each member.

        NOTE: Anything that can be a member of an ElementPool should have a
        corresponding IRelationsProvider adapter that yields a
        (member -> impacts -> pool) IRelation.

        """
        if type in (TAG_ALL, TAG_IMPACTED_BY):
            try:
                for element in self._adapted.getElements():
                    yield self.constructRelationTo(element, TAG_IMPACTED_BY)
            except Exception:
                LOG.exception(
                    "failed to get elements for %s",
                    self._adapted.getPrimaryId())
