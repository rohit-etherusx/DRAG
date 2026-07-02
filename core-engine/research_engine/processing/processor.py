"""Evidence processing.

Converts downloaded documents into the claim pipeline's inputs, in two stages:

1. **Passage extraction** (``OBJECTIVE.md`` module 4): each document is split
   into passages, scored against the subquestion it was retrieved for, and only
   the high-scoring passages become :class:`Evidence` items. Documents are
   never passed whole to an LLM. Deterministic.
2. **Claim extraction** (module 5): a :class:`ClaimExtractor` (LLM-backed when
   configured, heuristic otherwise) turns each document's evidence passages
   into typed :class:`ExtractedClaim`s.

The processor owns the strategy-independent concerns — id assignment, global
passage de-duplication, and provenance — so every evidence item remains
traceable to its document and source regardless of how claims were extracted.
"""
from __future__ import annotations

from research_engine.domain.models import Evidence, RawDocument
from research_engine.processing.extraction import ClaimExtractor, ExtractedClaim
from research_engine.ranking.passages import PassageSelector
from research_engine.utils import normalize_claim


class EvidenceProcessor:
    """Extracts evidence passages and typed claims from downloaded documents."""

    def __init__(
        self,
        extractor: ClaimExtractor,
        selector: PassageSelector | None = None,
    ) -> None:
        self._extractor = extractor
        self._selector = selector or PassageSelector()
        self._counter = 0
        self._seen_passages: set[str] = set()

    def process(
        self, documents: list[RawDocument], subquestion_text: str
    ) -> tuple[list[Evidence], list[ExtractedClaim]]:
        """Return (evidence passages, extracted claims) for ``documents``.

        Passage de-duplication is global across every document processed by
        this instance: a passage already seen (case/whitespace-insensitive) is
        skipped so repeated text doesn't inflate corroboration downstream.
        """
        all_evidence: list[Evidence] = []
        all_claims: list[ExtractedClaim] = []
        for document in documents:
            evidence = self._extract_evidence(document, subquestion_text)
            if not evidence:
                continue
            all_evidence.extend(evidence)
            all_claims.extend(self._extractor.extract(document, evidence))
        return all_evidence, all_claims

    def _extract_evidence(
        self, document: RawDocument, subquestion_text: str
    ) -> list[Evidence]:
        evidence: list[Evidence] = []
        passages = self._selector.top_passages(
            document.content, subquestion_text, document.query
        )
        for passage, score in passages:
            key = normalize_claim(passage)
            if not key or key in self._seen_passages:
                continue
            self._seen_passages.add(key)
            self._counter += 1
            evidence.append(
                Evidence(
                    id=f"ev-{self._counter}",
                    passage=passage,
                    document_id=document.id,
                    source_id=document.source.id,
                    task_id=document.task_id,
                    subquestion_id=document.subquestion_id,
                    relevance_score=score,
                )
            )
        return evidence
