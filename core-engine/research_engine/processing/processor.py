"""Evidence processing.

Converts raw documents into normalized :class:`Evidence` items: it splits
content into claims, de-duplicates them, extracts candidate entities, records
provenance, and flags conflicting claims. Every evidence item remains traceable
to its originating source and task.
"""
from __future__ import annotations

from research_engine.domain.models import Contradiction, Evidence, RawDocument
from research_engine.processing.extraction import ClaimExtractor, HeuristicClaimExtractor
from research_engine.utils import normalize_claim

_NEGATIONS = {"not", "no", "never", "cannot", "without", "lacks", "fails"}


class EvidenceProcessor:
    """Extracts and normalizes evidence from raw documents.

    Claim extraction is delegated to a :class:`ClaimExtractor` (heuristic by
    default, LLM-backed when configured). The processor owns the concerns that
    are strategy-independent: global de-duplication, id assignment, and
    provenance. This keeps every evidence item traceable to its source and task
    regardless of how claims were extracted.
    """

    def __init__(
        self,
        topic_keywords: list[str] | None = None,
        extractor: ClaimExtractor | None = None,
    ) -> None:
        self._extractor = extractor or HeuristicClaimExtractor(topic_keywords)
        self._counter = 0
        self._seen: set[str] = set()
        #: LLM-extracted relationships with provenance, accumulated across all
        #: ``process`` calls: (source, relation, target, evidence_ids).
        self._relationships: list[tuple[str, str, str, list[str]]] = []

    @property
    def relationships(self) -> list[tuple[str, str, str, list[str]]]:
        """Relationships extracted so far, tagged with supporting evidence ids."""
        return self._relationships

    def process(self, documents: list[RawDocument]) -> list[Evidence]:
        """Return de-duplicated evidence extracted from ``documents``.

        De-duplication is global across every document processed by this
        instance: a claim already seen (case/whitespace-insensitive) is skipped
        so repeated statements don't inflate confidence. Any relationships the
        extractor reports are accumulated (with provenance) on :attr:`relationships`.
        """
        evidence: list[Evidence] = []
        for document in documents:
            result = self._extractor.extract(document)
            doc_evidence_ids: list[str] = []
            for claim in result.claims:
                key = normalize_claim(claim.text)
                if not key or key in self._seen:
                    continue
                self._seen.add(key)
                self._counter += 1
                item = Evidence(
                    id=f"ev-{self._counter}",
                    claim=claim.text,
                    source_id=document.source.id,
                    task_id=document.task_id,
                    entities=claim.entities,
                )
                evidence.append(item)
                doc_evidence_ids.append(item.id)
            for rel in result.relationships:
                self._relationships.append(
                    (rel.source, rel.relation, rel.target, list(doc_evidence_ids))
                )
        return evidence

    def detect_contradictions(self, evidence: list[Evidence]) -> list[Contradiction]:
        """Flag pairs of claims that appear to conflict.

        Heuristic: two claims share substantial vocabulary but differ on the
        presence of a negation word. This is deliberately simple for v0.1 and is
        isolated here so it can be strengthened without touching callers.
        """
        contradictions: list[Contradiction] = []
        counter = 0
        for i in range(len(evidence)):
            words_i = _content_words(evidence[i].claim)
            neg_i = bool(words_i & _NEGATIONS)
            for j in range(i + 1, len(evidence)):
                words_j = _content_words(evidence[j].claim)
                neg_j = bool(words_j & _NEGATIONS)
                if neg_i == neg_j:
                    continue
                shared = (words_i - _NEGATIONS) & (words_j - _NEGATIONS)
                smaller = min(len(words_i - _NEGATIONS), len(words_j - _NEGATIONS)) or 1
                if len(shared) / smaller >= 0.6 and len(shared) >= 3:
                    counter += 1
                    contradictions.append(
                        Contradiction(
                            id=f"contra-{counter}",
                            description=(
                                "Potentially conflicting claims: "
                                f'"{evidence[i].claim}" vs "{evidence[j].claim}"'
                            ),
                            evidence_ids=[evidence[i].id, evidence[j].id],
                        )
                    )
        return contradictions


def _content_words(claim: str) -> set[str]:
    return {w.lower() for w in claim.replace(".", " ").split() if len(w) >= 3}
