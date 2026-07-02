"""Information gain analysis.

Research quality is measured by information gained, not by volume
(``OBJECTIVE.md`` principle 6). This analyzer measures how much every acquired
document — and every research-loop iteration — actually taught the engine, so
that redundant information is recognized, low-value acquisition is visible in
the audit trail, and the stopping engine can detect when searching has stopped
producing knowledge.

Per **document** (stamped onto the document):

* ``novelty_score`` — fraction of its claims that were new knowledge (by claim
  signature, the same identity normalization uses);
* ``redundancy_score`` — fraction that duplicated already-known claims;
* ``coverage_score`` — fraction of its claims serving still-open subquestions;
* ``evidence_density`` — claims contributed per evidence passage;
* ``importance_score`` — mean importance of the verified claims it supports.

Per **iteration** (an :class:`IterationRecord` in the session):

* ``novelty`` — fraction of the iteration's extracted claims that were new;
* ``knowledge_gain`` — the fraction of the current knowledge model that this
  iteration contributed: ``(claims_after - claims_before) / claims_after``,
  floored at zero (verification merges can shrink the model). One formula,
  directly interpretable, no tuned weights.

Everything here is a pure function of its inputs — deterministic and
explainable.
"""
from __future__ import annotations

from research_engine.domain.models import (
    Claim,
    Evidence,
    IterationRecord,
    RawDocument,
)
from research_engine.processing.extraction import ExtractedClaim
from research_engine.processing.normalizer import claim_signature


class InformationGainAnalyzer:
    """Measures what documents and iterations added to the knowledge model."""

    def analyze(
        self,
        *,
        iteration: int,
        search_tasks: int,
        new_documents: list[RawDocument],
        new_extracted: list[ExtractedClaim],
        prior_extracted: list[ExtractedClaim],
        evidence_by_id: dict[str, Evidence],
        open_subquestion_ids: set[str],
        verified_claims: list[Claim],
        claims_before: int,
        corroborated: int,
        confidence: float,
        gaps_open: int,
    ) -> IterationRecord:
        """Stamp gain scores on ``new_documents`` and record the iteration."""
        known = {claim_signature(c.text) for c in prior_extracted}
        novel_flags = self._novelty_flags(new_extracted, known)
        self._stamp_documents(
            new_documents,
            new_extracted,
            novel_flags,
            evidence_by_id,
            open_subquestion_ids,
            verified_claims,
        )

        claims_after = len(verified_claims)
        novelty = (
            sum(novel_flags) / len(novel_flags) if novel_flags else 0.0
        )
        growth = max(0, claims_after - claims_before)
        knowledge_gain = growth / claims_after if claims_after else 0.0
        return IterationRecord(
            iteration=iteration,
            search_tasks=search_tasks,
            documents_downloaded=len(new_documents),
            claims_before=claims_before,
            claims_after=claims_after,
            corroborated=corroborated,
            novelty=round(novelty, 4),
            knowledge_gain=round(knowledge_gain, 4),
            confidence=confidence,
            gaps_open=gaps_open,
        )

    @staticmethod
    def _novelty_flags(
        new_extracted: list[ExtractedClaim], known: set[str]
    ) -> list[bool]:
        """Whether each newly extracted claim was unknown before this iteration.

        A signature repeated *within* the new batch counts as novel once —
        the first occurrence taught the engine something, the rest did not.
        """
        seen = set(known)
        flags: list[bool] = []
        for claim in new_extracted:
            signature = claim_signature(claim.text)
            flags.append(bool(signature) and signature not in seen)
            seen.add(signature)
        return flags

    @staticmethod
    def _stamp_documents(
        documents: list[RawDocument],
        new_extracted: list[ExtractedClaim],
        novel_flags: list[bool],
        evidence_by_id: dict[str, Evidence],
        open_subquestion_ids: set[str],
        verified_claims: list[Claim],
    ) -> None:
        by_document: dict[str, list[tuple[ExtractedClaim, bool]]] = {}
        passages_per_document: dict[str, set[str]] = {}
        for claim, novel in zip(new_extracted, novel_flags):
            evidence = evidence_by_id.get(claim.evidence_id)
            if evidence is None:
                continue
            by_document.setdefault(evidence.document_id, []).append((claim, novel))
            passages_per_document.setdefault(evidence.document_id, set()).add(
                evidence.id
            )

        importance_by_document = _document_importance(
            verified_claims, evidence_by_id
        )

        for document in documents:
            contributions = by_document.get(document.id, [])
            if not contributions:
                # A document whose passages were all duplicates contributed
                # nothing: fully redundant.
                document.redundancy_score = 1.0
                continue
            total = len(contributions)
            novel_count = sum(1 for _claim, novel in contributions if novel)
            covering = sum(
                1
                for claim, _novel in contributions
                if _serves_open_subquestion(
                    claim, evidence_by_id, open_subquestion_ids
                )
            )
            passages = len(passages_per_document.get(document.id, set())) or 1
            document.novelty_score = round(novel_count / total, 4)
            document.redundancy_score = round(1.0 - novel_count / total, 4)
            document.coverage_score = round(covering / total, 4)
            document.evidence_density = round(total / passages, 4)
            document.importance_score = importance_by_document.get(document.id, 0.0)


def _serves_open_subquestion(
    claim: ExtractedClaim,
    evidence_by_id: dict[str, Evidence],
    open_subquestion_ids: set[str],
) -> bool:
    evidence = evidence_by_id.get(claim.evidence_id)
    return evidence is not None and evidence.subquestion_id in open_subquestion_ids


def _document_importance(
    verified_claims: list[Claim], evidence_by_id: dict[str, Evidence]
) -> dict[str, float]:
    """Mean importance of the verified claims each document supports."""
    totals: dict[str, list[float]] = {}
    for claim in verified_claims:
        documents = {
            evidence_by_id[eid].document_id
            for eid in claim.evidence_ids
            if eid in evidence_by_id
        }
        for document_id in documents:
            totals.setdefault(document_id, []).append(claim.importance)
    return {
        document_id: round(sum(values) / len(values), 4)
        for document_id, values in totals.items()
    }
