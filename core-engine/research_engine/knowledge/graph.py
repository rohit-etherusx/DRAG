"""Knowledge graph.

Builds and stores the entities and relationships discovered during research.
Entities are derived from evidence; relationships are inferred from co-occurrence
of entities within the same evidence item. The graph is the structured, long-term
memory of a session.
"""
from __future__ import annotations

from itertools import combinations

from research_engine.domain.models import Entity, Evidence, Relationship
from research_engine.utils import slugify


class KnowledgeGraph:
    """An entity/relationship graph built from evidence."""

    def __init__(self) -> None:
        self._entities: dict[str, Entity] = {}
        self._relationships: dict[str, Relationship] = {}

    def build(self, evidence: list[Evidence]) -> None:
        """Populate the graph from a list of evidence items."""
        for item in evidence:
            entity_ids = [self._upsert_entity(name, item.id) for name in item.entities]
            # Co-occurring entities within one evidence item are related.
            for a, b in combinations(sorted(set(entity_ids)), 2):
                self._upsert_relationship(a, b, item.id)

    @property
    def entities(self) -> list[Entity]:
        return list(self._entities.values())

    @property
    def relationships(self) -> list[Relationship]:
        return list(self._relationships.values())

    def neighbors(self, entity_id: str) -> list[str]:
        """Return ids of entities directly related to ``entity_id``."""
        out: list[str] = []
        for rel in self._relationships.values():
            if rel.source_entity_id == entity_id:
                out.append(rel.target_entity_id)
            elif rel.target_entity_id == entity_id:
                out.append(rel.source_entity_id)
        return out

    def _upsert_entity(self, name: str, evidence_id: str) -> str:
        entity_id = f"ent-{slugify(name)}"
        entity = self._entities.get(entity_id)
        if entity is None:
            entity = Entity(id=entity_id, name=name)
            self._entities[entity_id] = entity
        if evidence_id not in entity.evidence_ids:
            entity.evidence_ids.append(evidence_id)
        return entity_id

    def _upsert_relationship(self, a: str, b: str, evidence_id: str) -> None:
        rel_id = f"rel-{a}--{b}"
        rel = self._relationships.get(rel_id)
        if rel is None:
            rel = Relationship(id=rel_id, source_entity_id=a, target_entity_id=b)
            self._relationships[rel_id] = rel
        if evidence_id not in rel.evidence_ids:
            rel.evidence_ids.append(evidence_id)
