"""Evidence processing.

Converts raw documents into normalized :class:`Evidence` items: it splits
content into claims, de-duplicates them, extracts candidate entities, records
provenance, and flags conflicting claims. Every evidence item remains traceable
to its originating source and task.
"""
from __future__ import annotations

from research_engine.domain.models import Contradiction, Evidence, RawDocument
from research_engine.utils import extract_entity_names, normalize_claim, split_sentences

_NEGATIONS = {"not", "no", "never", "cannot", "without", "lacks", "fails"}


class EvidenceProcessor:
    """Extracts and normalizes evidence from raw documents."""

    def __init__(self, topic_keywords: list[str] | None = None) -> None:
        self._topic_keywords = topic_keywords or []
        self._counter = 0

    def process(self, documents: list[RawDocument]) -> list[Evidence]:
        """Return de-duplicated evidence extracted from ``documents``.

        De-duplication is global across the supplied documents: a claim already
        seen (case/whitespace-insensitive) is skipped so repeated statements
        don't inflate confidence.
        """
        evidence: list[Evidence] = []
        seen: set[str] = set()
        for document in documents:
            for sentence in split_sentences(document.content):
                key = normalize_claim(sentence)
                if not key or key in seen:
                    continue
                seen.add(key)
                self._counter += 1
                evidence.append(
                    Evidence(
                        id=f"ev-{self._counter}",
                        claim=sentence,
                        source_id=document.source.id,
                        task_id=document.task_id,
                        entities=extract_entity_names(sentence, self._topic_keywords),
                    )
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
