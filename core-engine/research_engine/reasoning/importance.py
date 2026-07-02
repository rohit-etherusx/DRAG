"""Claim importance estimation.

Not all information is equally valuable (``OBJECTIVE.md`` principle 5): core
concepts, relationships, and well-supported explanations must outrank
incidental facts, or low-value claims dominate reasoning, answers, and the
report. This module stamps a deterministic 0..1 ``importance`` on every
verified claim so downstream stages can rank and filter by it.

Importance is a pure function of four measurable factors:

* **type** — definitions, methods, and limitations teach more than a stray
  date; open questions assert nothing;
* **objective relevance** — how much of the claim's vocabulary appears in the
  research objective, subject, and subquestions;
* **centrality** — whether the claim concerns entities that the rest of the
  knowledge model keeps referring to;
* **corroboration** — independently confirmed knowledge outranks single-source
  assertions (uses the verification ``agreement``).

Importance is *not* confidence: a contradicted claim can be highly important
(it needs investigating) while its confidence is low.
"""
from __future__ import annotations

from research_engine.domain.models import Claim, ClaimType, Entity, ResearchPlan
from research_engine.utils import keywords

#: Factor weights (sum to 1.0). Relevance to the objective and the claim's
#: kind dominate; centrality and corroboration modulate.
_WEIGHTS = {
    "type": 0.3,
    "relevance": 0.3,
    "centrality": 0.2,
    "corroboration": 0.2,
}

#: How much each claim type contributes to understanding, independent of
#: content. Definitions and methods carry the concepts everything else builds
#: on; open questions assert nothing (they surface in open questions instead).
_TYPE_VALUE = {
    ClaimType.DEFINITION: 1.0,
    ClaimType.METHOD: 0.9,
    ClaimType.LIMITATION: 0.8,
    ClaimType.FACT: 0.7,
    ClaimType.NUMERICAL: 0.7,
    ClaimType.DATE: 0.6,
    ClaimType.ASSUMPTION: 0.6,
    ClaimType.OPEN_QUESTION: 0.2,
}


class ImportanceModel:
    """Stamps deterministic importance scores onto verified claims."""

    def stamp(
        self, claims: list[Claim], plan: ResearchPlan, entities: list[Entity]
    ) -> None:
        """Set ``claim.importance`` for every claim, in place."""
        objective_terms = _objective_terms(plan)
        reference_counts = {e.name.lower(): len(e.claim_ids) for e in entities}
        max_references = max(reference_counts.values(), default=1) or 1

        for claim in claims:
            factors = {
                "type": _TYPE_VALUE.get(claim.claim_type, 0.5),
                "relevance": _relevance(claim.text, objective_terms),
                "centrality": _centrality(
                    claim.entities, reference_counts, max_references
                ),
                "corroboration": min(1.0, claim.agreement),
            }
            score = sum(_WEIGHTS[name] * value for name, value in factors.items())
            claim.importance = round(min(1.0, max(0.0, score)), 4)


def _objective_terms(plan: ResearchPlan) -> set[str]:
    """Content terms of the research objective, subject, and subquestions."""
    text_parts = [plan.objective, plan.subject, plan.question]
    text_parts.extend(sq.question for sq in plan.subquestions)
    text_parts.extend(plan.expected_entities)
    terms: set[str] = set()
    for part in text_parts:
        terms.update(keywords(part, limit=32))
    return terms


def _relevance(text: str, objective_terms: set[str]) -> float:
    """Fraction of the claim's content words that serve the objective."""
    claim_terms = set(keywords(text, limit=32))
    if not claim_terms or not objective_terms:
        return 0.0
    return len(claim_terms & objective_terms) / len(claim_terms)


def _centrality(
    entity_names: list[str],
    reference_counts: dict[str, int],
    max_references: int,
) -> float:
    """How central the claim's most-referenced entity is to the knowledge model."""
    best = max(
        (reference_counts.get(name.lower(), 0) for name in entity_names),
        default=0,
    )
    return best / max_references
