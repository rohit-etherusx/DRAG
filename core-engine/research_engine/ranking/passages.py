"""Passage selection.

Once a document is accepted, most of its text is still irrelevant to the research
angle. Sending the whole document to the LLM for claim extraction wastes tokens.
This module splits a document into passages, keeps only the most relevant ones,
and returns the reduced text — so expensive extraction only ever sees high-value
content.

It is deliberately fail-open: if no passage clears the relevance bar (e.g. very
short documents, or an unusual layout), the full original text is returned rather
than risk dropping a genuinely useful document to zero content.
"""
from __future__ import annotations

import re

from research_engine.utils import keywords

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9'\-]+")
_PARA_RE = re.compile(r"\n\s*\n")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


class PassageSelector:
    """Reduces a document to its passages most relevant to the topic/query."""

    def __init__(
        self,
        max_passages: int = 6,
        min_relevance: float = 0.05,
        sentences_per_passage: int = 3,
    ) -> None:
        self._max_passages = max(1, max_passages)
        self._min_relevance = min_relevance
        self._sentences_per_passage = max(1, sentences_per_passage)

    def select(self, content: str, topic: str, query: str = "") -> str:
        """Return the concatenation of the most relevant passages in ``content``.

        Passages are kept in their original order (so the reduced text still
        reads coherently). Falls open to the full content when nothing qualifies.
        """
        kept = self.top_passages(content, topic, query)
        return "\n\n".join(passage for passage, _score in kept)

    def top_passages(
        self, content: str, topic: str, query: str = ""
    ) -> list[tuple[str, float]]:
        """Return the most relevant ``(passage, score)`` pairs in ``content``.

        Passages are returned in their original document order. Fails open: when
        nothing qualifies (very short documents, unusual layout, or no terms to
        rank on) the full content is returned as a single passage rather than
        risk dropping a genuinely useful document to zero evidence.
        """
        content = content.strip()
        if not content:
            return []

        terms = self._terms(topic, query)
        passages = self._split(content)
        if not terms or len(passages) <= 1:
            return [(content, _passage_score(content, terms) if terms else 1.0)]

        scored = [
            (index, passage, _passage_score(passage, terms))
            for index, passage in enumerate(passages)
        ]
        qualifying = [s for s in scored if s[2] >= self._min_relevance]
        if not qualifying:
            return [(content, _passage_score(content, terms))]  # fail open

        # Take the best N, then restore original order for readability.
        qualifying.sort(key=lambda s: s[2], reverse=True)
        kept = sorted(qualifying[: self._max_passages], key=lambda s: s[0])
        return [(passage, round(score, 4)) for _, passage, score in kept]

    def _terms(self, topic: str, query: str) -> set[str]:
        terms = {k.lower() for k in keywords(topic)}
        terms.update(k.lower() for k in keywords(query))
        return {t for t in terms if len(t) >= 3}

    def _split(self, content: str) -> list[str]:
        """Split into paragraphs; fall back to fixed-size sentence windows."""
        paragraphs = [p.strip() for p in _PARA_RE.split(content) if p.strip()]
        if len(paragraphs) > 1:
            return paragraphs

        sentences = [s.strip() for s in _SENTENCE_RE.split(content) if s.strip()]
        if len(sentences) <= 1:
            return [content]
        windows: list[str] = []
        for start in range(0, len(sentences), self._sentences_per_passage):
            window = sentences[start : start + self._sentences_per_passage]
            windows.append(" ".join(window))
        return windows


def _passage_score(passage: str, terms: set[str]) -> float:
    tokens = set(_TOKEN_RE.findall(passage.lower()))
    if not tokens:
        return 0.0
    matched = sum(1 for t in terms if t in tokens)
    return matched / len(terms)
