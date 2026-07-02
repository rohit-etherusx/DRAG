"""Document relevance scoring.

Assigns each retrieved document a 0..1 score for how relevant it is to the
research objective, *before* it is processed. Documents that score below the
configured threshold are rejected by the ranker, so weakly-related material never
enters the evidence pipeline or the knowledge graph.

Two interchangeable strategies implement :class:`RelevanceScorer`:

* :class:`HeuristicRelevanceScorer` — deterministic term-overlap coverage between
  the topic/query terms and the document text (title-weighted). Zero-cost,
  offline, always available; the default and the fallback.
* :class:`LLMRelevanceScorer` — asks the LLM to rate relevance directly, for
  higher precision when a model is configured. Falls back to the heuristic on any
  unusable response.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod

from research_engine.domain.models import RawDocument
from research_engine.logging_setup import get_logger
from research_engine.providers.base import LLMProvider
from research_engine.utils import keywords

_log = get_logger("ranking.relevance")

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9'\-]+")


class RelevanceScorer(ABC):
    """Scores a document's topical relevance to the research objective."""

    @abstractmethod
    def score(self, document: RawDocument, topic: str) -> float:
        """Return a 0..1 relevance score for ``document`` given ``topic``."""
        raise NotImplementedError


class HeuristicRelevanceScorer(RelevanceScorer):
    """Deterministic relevance via topic-term coverage (title-weighted).

    The score combines how many distinct topic/query terms appear in the body
    with how many appear in the title (titles are strong relevance signals).
    Fully reproducible and free.
    """

    def __init__(self, topic_keywords: list[str] | None = None) -> None:
        self._topic_keywords = [k.lower() for k in (topic_keywords or [])]

    def _terms(self, document: RawDocument, topic: str) -> set[str]:
        terms = set(self._topic_keywords)
        terms.update(k.lower() for k in keywords(topic))
        # The per-document query captures the specific research angle.
        terms.update(k.lower() for k in keywords(document.query))
        return {t for t in terms if len(t) >= 3}

    def score(self, document: RawDocument, topic: str) -> float:
        terms = self._terms(document, topic)
        if not terms:
            # Nothing to match on — fail open so we never reject blindly.
            return 1.0

        body_tokens = set(_TOKEN_RE.findall(document.content.lower()))
        title_tokens = set(_TOKEN_RE.findall(document.title.lower()))

        matched_body = sum(1 for t in terms if t in body_tokens)
        matched_title = sum(1 for t in terms if t in title_tokens)

        coverage = matched_body / len(terms)
        title_cov = matched_title / len(terms)
        return round(min(1.0, 0.7 * coverage + 0.3 * title_cov), 4)


class LLMRelevanceScorer(RelevanceScorer):
    """Rates relevance with an LLM, falling back to a heuristic scorer."""

    def __init__(
        self,
        llm: LLMProvider,
        fallback: RelevanceScorer,
        max_input_chars: int = 1200,
    ) -> None:
        self._llm = llm
        self._fallback = fallback
        self._max_input_chars = max_input_chars

    def score(self, document: RawDocument, topic: str) -> float:
        if not self._llm.available:
            return self._fallback.score(document, topic)

        excerpt = document.content[: self._max_input_chars]
        prompt = (
            f"Rate how relevant the following document is to research on "
            f"'{topic}'. Consider only genuine topical relevance, not superficial "
            f"keyword overlap.\n\n"
            f"TITLE: {document.title}\n"
            f"EXCERPT:\n{excerpt}\n\n"
            f"Reply with ONLY a number from 0.0 (irrelevant) to 1.0 (highly "
            f"relevant)."
        )
        raw = self._llm.generate(
            prompt, system="You rate document relevance as a single number 0..1."
        )
        value = _parse_score(raw)
        if value is None:
            _log.debug("LLM relevance unusable for %s; heuristic fallback", document.id)
            return self._fallback.score(document, topic)
        return value


def _parse_score(raw: str | None) -> float | None:
    """Extract the first 0..1 float from an LLM response, clamped."""
    if not raw:
        return None
    match = re.search(r"[01](?:\.\d+)?|0?\.\d+", raw.strip())
    if not match:
        return None
    try:
        return max(0.0, min(1.0, float(match.group(0))))
    except ValueError:
        return None
