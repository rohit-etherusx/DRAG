"""Curiosity engine.

Determines what the engine does not yet know but should (``ARCHITECTURE.md``
v0.5). After every knowledge update it inspects the knowledge model and turns
what is *missing* into explicit :class:`KnowledgeGap` items — each with a
suggested search query and a priority — instead of merely reporting the gaps
at the end. The adaptive planner converts open gaps into the next iteration's
search tasks: curiosity is what makes missing information something the agent
investigates rather than something the report apologizes for.

Every reasoning iteration checks for (``IMPLEMENTATION.md`` curiosity rules):

* **missing evidence** — active subquestions with no verified claims at all;
* **uncorroborated knowledge** — subquestions supported only by one source;
* **missing definitions** — entities the knowledge model keeps referring to
  but never defines;
* **missing relationships** — central entities isolated from every other
  entity (no claim connects them to the rest of the model);
* **contradictions** — conflicting claims that need investigation;
* **missing primary sources** — important claims resting only on
  low-authority sources.

Discovery is deterministic: the same knowledge model yields the same gaps.
"""
from __future__ import annotations

from research_engine.domain.models import (
    Claim,
    ClaimType,
    Contradiction,
    Entity,
    GapKind,
    KnowledgeGap,
    ResearchPlan,
    Source,
    SubQuestion,
)
from research_engine.utils import keywords

#: An entity is "central enough" to deserve a definition/relationship gap when
#: at least this many claims reference it.
_MIN_ENTITY_REFERENCES = 3
#: Sources at or above this authority count as primary/authoritative.
_PRIMARY_AUTHORITY = 0.6
#: Claims at or above this importance deserve primary-source corroboration.
_IMPORTANT_CLAIM = 0.6
#: Cap on entity-driven gaps per discovery pass, so one iteration's gaps stay
#: focused on the most central concepts.
_MAX_ENTITY_GAPS = 5

#: Gap priorities: what closing each kind of gap contributes to the objective.
_PRIORITY = {
    GapKind.MISSING_EVIDENCE: 0.9,
    GapKind.CONTRADICTION: 0.8,
    GapKind.MISSING_DEFINITION: 0.7,
    GapKind.UNCORROBORATED: 0.6,
    GapKind.MISSING_RELATIONSHIP: 0.5,
    GapKind.MISSING_PRIMARY_SOURCE: 0.5,
}


class CuriosityEngine:
    """Discovers knowledge gaps in the current knowledge model."""

    def discover(
        self,
        *,
        plan: ResearchPlan,
        claims: list[Claim],
        contradictions: list[Contradiction],
        entities: list[Entity],
        sources: dict[str, Source],
        active_subquestion_ids: set[str],
    ) -> list[KnowledgeGap]:
        """Return the gaps present in the knowledge model, ids unassigned.

        The research state assigns ids and de-duplicates against gaps already
        discovered in earlier iterations.
        """
        gaps: list[KnowledgeGap] = []
        gaps.extend(_subquestion_gaps(plan.subquestions, claims, active_subquestion_ids))
        gaps.extend(_entity_gaps(claims, entities, plan))
        gaps.extend(_contradiction_gaps(contradictions, claims))
        gaps.extend(_primary_source_gaps(claims, sources))
        return gaps


def _subquestion_gaps(
    subquestions: list[SubQuestion],
    claims: list[Claim],
    active_subquestion_ids: set[str],
) -> list[KnowledgeGap]:
    """Missing or uncorroborated evidence for still-active subquestions."""
    gaps: list[KnowledgeGap] = []
    for subquestion in subquestions:
        if subquestion.id not in active_subquestion_ids:
            continue
        supporting = [
            c
            for c in claims
            if subquestion.id in c.subquestion_ids
            and c.claim_type is not ClaimType.OPEN_QUESTION
        ]
        base_query = " ".join(keywords(subquestion.question, limit=6))
        if not supporting:
            gaps.append(
                _gap(
                    GapKind.MISSING_EVIDENCE,
                    f"No verified evidence answers: {subquestion.question}",
                    suggested_query=base_query,
                    subquestion_id=subquestion.id,
                )
            )
        elif all(c.supporting_sources < 2 for c in supporting):
            gaps.append(
                _gap(
                    GapKind.UNCORROBORATED,
                    "Only single-source evidence exists for: "
                    f"{subquestion.question}",
                    suggested_query=f"{base_query} evidence",
                    subquestion_id=subquestion.id,
                )
            )
    return gaps


def _entity_gaps(
    claims: list[Claim], entities: list[Entity], plan: ResearchPlan
) -> list[KnowledgeGap]:
    """Missing definitions and missing relationships for central entities."""
    central = [
        e for e in entities if len(e.claim_ids) >= _MIN_ENTITY_REFERENCES
    ]
    central.sort(key=lambda e: (-len(e.claim_ids), e.name))

    defined = {
        name.lower()
        for claim in claims
        if claim.claim_type is ClaimType.DEFINITION
        for name in claim.entities
    }
    connected = _connected_entities(claims)

    gaps: list[KnowledgeGap] = []
    for entity in central[:_MAX_ENTITY_GAPS]:
        primary_subquestion = _primary_subquestion(entity, claims)
        if entity.name.lower() not in defined:
            gaps.append(
                _gap(
                    GapKind.MISSING_DEFINITION,
                    f"'{entity.name}' is referenced by {len(entity.claim_ids)} "
                    "claims but never defined.",
                    suggested_query=f"what is {entity.name}",
                    subquestion_id=primary_subquestion,
                    entity=entity.name,
                )
            )
        elif entity.name.lower() not in connected:
            gaps.append(
                _gap(
                    GapKind.MISSING_RELATIONSHIP,
                    f"'{entity.name}' is central but unconnected — no claim "
                    "relates it to the rest of the knowledge model.",
                    suggested_query=f"{entity.name} role in {plan.subject}",
                    subquestion_id=primary_subquestion,
                    entity=entity.name,
                )
            )
    return gaps


def _contradiction_gaps(
    contradictions: list[Contradiction], claims: list[Claim]
) -> list[KnowledgeGap]:
    claims_by_id = {c.id: c for c in claims}
    gaps: list[KnowledgeGap] = []
    for contradiction in contradictions:
        texts = " ".join(
            claims_by_id[cid].text
            for cid in contradiction.claim_ids
            if cid in claims_by_id
        )
        gaps.append(
            _gap(
                GapKind.CONTRADICTION,
                f"Sources conflict: {contradiction.description}",
                suggested_query=" ".join(keywords(texts, limit=6)),
                subquestion_id=_first_subquestion(contradiction, claims_by_id),
                entity=contradiction.id,
            )
        )
    return gaps


def _primary_source_gaps(
    claims: list[Claim], sources: dict[str, Source]
) -> list[KnowledgeGap]:
    """Important claims that rest only on low-authority sources."""
    gaps: list[KnowledgeGap] = []
    for claim in claims:
        if claim.importance < _IMPORTANT_CLAIM:
            continue
        authorities = [
            sources[sid].authority for sid in claim.source_ids if sid in sources
        ]
        if not authorities or max(authorities) >= _PRIMARY_AUTHORITY:
            continue
        gaps.append(
            _gap(
                GapKind.MISSING_PRIMARY_SOURCE,
                "An important claim rests only on low-authority sources: "
                f"{claim.text}",
                suggested_query=" ".join(keywords(claim.text, limit=6))
                + " research",
                subquestion_id=claim.subquestion_ids[0]
                if claim.subquestion_ids
                else "",
                entity=claim.id,
            )
        )
    return gaps


def _gap(
    kind: GapKind,
    description: str,
    *,
    suggested_query: str,
    subquestion_id: str = "",
    entity: str = "",
) -> KnowledgeGap:
    return KnowledgeGap(
        id="",
        kind=kind,
        description=description,
        suggested_query=suggested_query.strip(),
        subquestion_id=subquestion_id,
        entity=entity,
        priority=_PRIORITY[kind],
    )


def _connected_entities(claims: list[Claim]) -> set[str]:
    """Entities that co-occur with another entity in at least one claim."""
    connected: set[str] = set()
    for claim in claims:
        names = {name.lower() for name in claim.entities}
        if len(names) >= 2:
            connected.update(names)
    return connected


def _primary_subquestion(entity: Entity, claims: list[Claim]) -> str:
    wanted = set(entity.claim_ids)
    for claim in claims:
        if claim.id in wanted and claim.subquestion_ids:
            return claim.subquestion_ids[0]
    return ""


def _first_subquestion(
    contradiction: Contradiction, claims_by_id: dict[str, Claim]
) -> str:
    for claim_id in contradiction.claim_ids:
        claim = claims_by_id.get(claim_id)
        if claim and claim.subquestion_ids:
            return claim.subquestion_ids[0]
    return ""
