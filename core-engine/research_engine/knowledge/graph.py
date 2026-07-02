"""Evidence graph.

The engine's reasoning memory (``OBJECTIVE.md`` module 8). Unlike the entity
graph it replaces, the **claim** is the primary node; documents, evidence
passages, and entities are secondary nodes that give claims context and
provenance. Edges are typed:

* ``supports`` — evidence passage → the claim extracted from it;
* ``references`` — evidence → its containing document; claim → an entity it
  mentions;
* ``defines`` — a definition claim → the entity it defines;
* ``contradicts`` — claim → conflicting claim (from verification);
* ``extends`` — a numerical/date detail claim → the definition claim it adds
  precision to (shared entity);
* ``depends_on`` — a method claim → an assumption claim it rests on (shared
  entity).

Construction is fully deterministic: identical claims and evidence always
produce the identical graph.
"""
from __future__ import annotations

from itertools import combinations

from research_engine.domain.models import (
    Claim,
    ClaimType,
    Entity,
    Evidence,
    EdgeRelation,
    GraphEdge,
    GraphNode,
)
from research_engine.utils import slugify


class EvidenceGraph:
    """A typed graph over claims, evidence, documents, and entities."""

    def __init__(self) -> None:
        self._nodes: dict[str, GraphNode] = {}
        self._edges: dict[tuple[str, str, str], GraphEdge] = {}
        self._entities: dict[str, Entity] = {}
        self._claims: list[Claim] = []

    def build(self, claims: list[Claim], evidence: list[Evidence]) -> None:
        """Populate the graph from verified claims and their evidence."""
        self._claims = list(claims)
        evidence_by_id = {e.id: e for e in evidence}

        for claim in claims:
            self._add_node("claim", claim.id, claim.text)
            self._link_provenance(claim, evidence_by_id)
            self._link_entities(claim)
            for other_id in claim.contradicts:
                self._add_edge(
                    _node_id("claim", claim.id),
                    _node_id("claim", other_id),
                    EdgeRelation.CONTRADICTS,
                )
        self._link_claim_structure()

    # -- construction -------------------------------------------------------

    def _link_provenance(
        self, claim: Claim, evidence_by_id: dict[str, Evidence]
    ) -> None:
        """evidence --supports--> claim; evidence --references--> document."""
        for evidence_id in claim.evidence_ids:
            item = evidence_by_id.get(evidence_id)
            if item is None:
                continue
            passage_label = item.passage[:80]
            self._add_node("evidence", item.id, passage_label)
            self._add_edge(
                _node_id("evidence", item.id),
                _node_id("claim", claim.id),
                EdgeRelation.SUPPORTS,
            )
            self._add_node("document", item.document_id, item.document_id)
            self._add_edge(
                _node_id("evidence", item.id),
                _node_id("document", item.document_id),
                EdgeRelation.REFERENCES,
            )

    def _link_entities(self, claim: Claim) -> None:
        """claim --defines/references--> entity; upsert the entity itself."""
        for index, name in enumerate(claim.entities):
            entity_id = self._upsert_entity(name, claim.id)
            defines = claim.claim_type is ClaimType.DEFINITION and index == 0
            self._add_edge(
                _node_id("claim", claim.id),
                _node_id("entity", entity_id),
                EdgeRelation.DEFINES if defines else EdgeRelation.REFERENCES,
            )

    def _link_claim_structure(self) -> None:
        """Derive extends / depends_on edges between claims sharing an entity."""
        for entity in self._entities.values():
            members = [c for c in self._claims if c.id in entity.claim_ids]
            for a, b in combinations(members, 2):
                self._structural_edge(a, b)
                self._structural_edge(b, a)

    def _structural_edge(self, a: Claim, b: Claim) -> None:
        """Add a --extends/depends_on--> b when their types imply structure."""
        detail_types = {ClaimType.NUMERICAL, ClaimType.DATE}
        if a.claim_type in detail_types and b.claim_type is ClaimType.DEFINITION:
            self._add_edge(
                _node_id("claim", a.id), _node_id("claim", b.id), EdgeRelation.EXTENDS
            )
        if a.claim_type is ClaimType.METHOD and b.claim_type is ClaimType.ASSUMPTION:
            self._add_edge(
                _node_id("claim", a.id),
                _node_id("claim", b.id),
                EdgeRelation.DEPENDS_ON,
            )

    def _upsert_entity(self, name: str, claim_id: str) -> str:
        entity_id = f"ent-{slugify(name)}"
        entity = self._entities.get(entity_id)
        if entity is None:
            entity = Entity(id=entity_id, name=name)
            self._entities[entity_id] = entity
            self._add_node("entity", entity_id, name)
        if claim_id and claim_id not in entity.claim_ids:
            entity.claim_ids.append(claim_id)
        return entity_id

    def _add_node(self, kind: str, ref_id: str, label: str) -> None:
        node_id = _node_id(kind, ref_id)
        if node_id not in self._nodes:
            self._nodes[node_id] = GraphNode(
                id=node_id, kind=kind, label=label, ref_id=ref_id
            )

    def _add_edge(self, source_id: str, target_id: str, relation: EdgeRelation) -> None:
        if source_id == target_id:
            return
        key = (source_id, target_id, relation.value)
        if key in self._edges:
            return
        self._edges[key] = GraphEdge(
            id=f"edge-{len(self._edges) + 1}",
            source_id=source_id,
            target_id=target_id,
            relation=relation,
        )

    # -- query surface (used by reasoning) -----------------------------------

    @property
    def nodes(self) -> list[GraphNode]:
        return list(self._nodes.values())

    @property
    def edges(self) -> list[GraphEdge]:
        return list(self._edges.values())

    @property
    def entities(self) -> list[Entity]:
        return list(self._entities.values())

    @property
    def claims(self) -> list[Claim]:
        return list(self._claims)

    def claims_for_entity(self, name: str) -> list[Claim]:
        """All claims that mention the entity ``name``."""
        entity = self._entities.get(f"ent-{slugify(name)}")
        if entity is None:
            return []
        wanted = set(entity.claim_ids)
        return [c for c in self._claims if c.id in wanted]

    def central_entities(self, limit: int = 5) -> list[Entity]:
        """Entities referenced by the most claims (research focal points)."""
        ranked = sorted(
            self._entities.values(),
            key=lambda e: (len(e.claim_ids), e.name),
            reverse=True,
        )
        return ranked[:limit]

    def edges_by_relation(self, relation: EdgeRelation) -> list[GraphEdge]:
        return [e for e in self._edges.values() if e.relation is relation]


def _node_id(kind: str, ref_id: str) -> str:
    return f"n-{kind}-{ref_id}"
