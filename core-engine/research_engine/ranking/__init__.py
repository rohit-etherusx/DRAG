"""Candidate evaluation, authority scoring, and passage selection.

This package is the *evidence-quality gate* of the pipeline. The
:class:`CandidateEvaluator` sits between retrieval and download: it scores
search-result metadata (title, snippet, URL) for topical relevance and source
authority and rejects irrelevant results *before* any bandwidth is spent on
them. The :class:`PassageSelector` then reduces each downloaded document to its
relevant passages, so only high-value text reaches claim extraction.

All scoring here is deterministic and reproducible.
"""
from research_engine.ranking.authority import SourceAuthorityScorer
from research_engine.ranking.evaluator import CandidateEvaluator, EvaluationOutcome
from research_engine.ranking.passages import PassageSelector

__all__ = [
    "SourceAuthorityScorer",
    "CandidateEvaluator",
    "EvaluationOutcome",
    "PassageSelector",
]
