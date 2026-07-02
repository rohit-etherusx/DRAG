"""Document ranker — the evidence-quality gate.

Combines authority scoring, relevance scoring, threshold filtering, and passage
selection into a single stage the orchestrator runs between collection and
processing. For each retrieved document it:

1. scores source authority and stamps it onto the shared
   :class:`~research_engine.domain.models.Source` (feeds confidence, and the
   report);
2. scores topical relevance and stamps it onto the document;
3. rejects the document if relevance is below the threshold (or, optionally,
   authority is below ``min_authority``) — rejected documents never reach
   processing or the knowledge graph;
4. reduces each accepted document to its most relevant passages (token savings),
   returning a copy so the original full-text document is preserved for the record.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from research_engine.domain.models import RawDocument
from research_engine.logging_setup import get_logger
from research_engine.ranking.authority import SourceAuthorityScorer
from research_engine.ranking.passages import PassageSelector
from research_engine.ranking.relevance import HeuristicRelevanceScorer, RelevanceScorer

if TYPE_CHECKING:  # avoid import cycles / hard deps at runtime
    from research_engine.config import EngineConfig
    from research_engine.providers.base import LLMProvider

_log = get_logger("ranking.ranker")


@dataclass
class RankOutcome:
    """Result of ranking a batch of documents."""

    #: Documents that passed filtering, reduced to their relevant passages.
    accepted: list[RawDocument]
    #: Number of documents rejected as insufficiently relevant.
    rejected: int


class DocumentRanker:
    """Scores, filters, and trims retrieved documents before processing."""

    def __init__(
        self,
        topic: str,
        authority_scorer: SourceAuthorityScorer,
        relevance_scorer: RelevanceScorer,
        passage_selector: PassageSelector,
        *,
        relevance_threshold: float = 0.12,
        min_authority: float = 0.0,
        enabled: bool = True,
    ) -> None:
        self._topic = topic
        self._authority = authority_scorer
        self._relevance = relevance_scorer
        self._passages = passage_selector
        self._relevance_threshold = relevance_threshold
        self._min_authority = min_authority
        self._enabled = enabled

    def rank(self, documents: list[RawDocument]) -> RankOutcome:
        """Rank ``documents``; return accepted (trimmed) docs + rejected count."""
        if not self._enabled:
            return RankOutcome(accepted=list(documents), rejected=0)

        accepted: list[RawDocument] = []
        rejected = 0
        for document in documents:
            # 1-2. Authority + relevance, stamped onto the original objects so the
            # full record (session.raw_documents / sources) carries the scores.
            authority, tier, domain = self._authority.score(document.source)
            document.source.domain = domain
            document.source.authority = authority
            document.source.authority_tier = tier

            relevance = self._relevance.score(document, self._topic)
            document.relevance_score = relevance

            # 3. Reject insufficiently relevant (or, if gated, low-authority) docs.
            if relevance < self._relevance_threshold or authority < self._min_authority:
                rejected += 1
                _log.debug(
                    "Rejected %s (relevance=%.3f, authority=%.2f, %s)",
                    document.source.id,
                    relevance,
                    authority,
                    tier,
                )
                continue

            # 4. Trim to relevant passages; keep the original document untouched.
            reduced = self._passages.select(
                document.content, self._topic, document.query
            )
            accepted.append(replace(document, content=reduced))

        return RankOutcome(accepted=accepted, rejected=rejected)


def build_ranker(
    config: "EngineConfig",
    topic: str,
    topic_keywords: list[str] | None = None,
    llm: "LLMProvider | None" = None,
) -> DocumentRanker:
    """Assemble a :class:`DocumentRanker` from configuration.

    Relevance scoring defaults to the deterministic heuristic (free and
    reproducible). An LLM relevance scorer is available as a drop-in but is not
    enabled by default, keeping runs cheap and reproducible.
    """
    heuristic = HeuristicRelevanceScorer(topic_keywords)
    relevance: RelevanceScorer = heuristic
    passages = PassageSelector(
        max_passages=config.max_passages,
        min_relevance=config.passage_min_relevance,
    )
    return DocumentRanker(
        topic,
        SourceAuthorityScorer(),
        relevance,
        passages,
        relevance_threshold=config.relevance_threshold,
        min_authority=config.min_authority,
        enabled=config.ranking_enabled,
    )
