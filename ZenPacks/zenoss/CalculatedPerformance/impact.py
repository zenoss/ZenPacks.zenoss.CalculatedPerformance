from zope.interface import implements
from zope.component import adapts

from ZenPacks.zenoss.Impact.impactd.interfaces import IRelationshipDataProvider
from ZenPacks.zenoss.Impact.impactd.relations import ImpactEdge
from ZenPacks.zenoss.CalculatedPerformance.ElementPool import ElementPool
from Products.ZenUtils.guid.interfaces import IGlobalIdentifier

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
            yield ImpactEdge(IGlobalIdentifier(element).getGUID(), poolGuid, "ElementPoolImpact")

