##############################################################################
#
# Copyright (C) Zenoss, Inc. 2014-2018, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

from zope.interface import implements
from zope.component import adapts

from Products.ZenUtils.guid.interfaces import IGlobalIdentifier

from ZenPacks.zenoss.Impact.impactd.interfaces import IRelationshipDataProvider
from ZenPacks.zenoss.Impact.impactd.relations import ImpactEdge

from ZenPacks.zenoss.CalculatedPerformance.ElementPool import ElementPool


class ElementPoolRelationsProvider:
    implements(IRelationshipDataProvider)
    adapts(ElementPool)

    def __init__(self, adapted):
        self._object = adapted

    def belongsInImpactGraph(self):
        return True

    def getEdges(self):
        pool = self._object
        poolGuid = IGlobalIdentifier(pool).getGUID()

        for element in pool.getElements():
            yield ImpactEdge(
                IGlobalIdentifier(element).getGUID(),
                poolGuid,
                "ElementPoolImpact")
