"""Ranking, authority scoring, and relevance filtering (v0.3).

This package is the *evidence-quality gate* that sits between collection and
processing. It scores each retrieved document for topical relevance and source
authority, rejects documents that are not genuinely relevant to the research
objective (so they never pollute processing or the knowledge graph), and reduces
each accepted document to its relevant passages (so only high-value text reaches
the expensive LLM extraction stage).

Every scorer sits behind an interface, so a deterministic heuristic (the default,
used offline and in tests) or an LLM-backed scorer can be swapped in without
touching the orchestrator.
"""
from research_engine.ranking.authority import SourceAuthorityScorer
from research_engine.ranking.passages import PassageSelector
from research_engine.ranking.ranker import DocumentRanker, RankOutcome, build_ranker
from research_engine.ranking.relevance import (
    HeuristicRelevanceScorer,
    LLMRelevanceScorer,
    RelevanceScorer,
)

__all__ = [
    "SourceAuthorityScorer",
    "PassageSelector",
    "DocumentRanker",
    "RankOutcome",
    "build_ranker",
    "RelevanceScorer",
    "HeuristicRelevanceScorer",
    "LLMRelevanceScorer",
]
