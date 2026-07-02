"""Claim clustering.

Groups equivalent claims — the same assertion made in different words by
different sources — so verification can compare *claims against claims*, never
documents. Clustering is deterministic: two claims are considered equivalent
when their content-word sets are sufficiently similar (Jaccard overlap above a
threshold). This is domain-agnostic and reproducible; an LLM-based semantic
clusterer could be substituted behind the same method signature later without
changing callers.

Exact-duplicate wordings have already been merged by the claim normalizer;
clustering catches the fuzzier matches (word order, minor additions) that a
signature comparison cannot.
"""
from __future__ import annotations

import re

from research_engine.domain.models import Claim

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9'\-]+")
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "as",
    "by", "at", "from", "is", "are", "was", "were", "be", "been", "being", "this",
    "that", "these", "those", "it", "its", "into", "also", "such", "which", "can",
    "may", "has", "have", "had", "not", "but", "than", "then", "there",
}
#: Words that flip a claim's polarity. Claims with different polarity must
#: never be treated as equivalent — "X is effective" and "X is not effective"
#: are a *contradiction*, not a corroboration.
_NEGATIONS = {"not", "no", "never", "cannot", "without", "lacks", "fails"}


class ClaimClusterer:
    """Clusters equivalent claims (deterministic token-set similarity)."""

    def __init__(self, similarity_threshold: float = 0.6, min_tokens: int = 3) -> None:
        self._threshold = similarity_threshold
        self._min_tokens = min_tokens

    def cluster(self, claims: list[Claim]) -> list[list[Claim]]:
        """Group ``claims`` into equivalence clusters, in first-seen order."""
        # (token_set, polarity, [claims]) accumulators, in first-seen order.
        buckets: list[tuple[set[str], bool, list[Claim]]] = []
        for claim in claims:
            tokens = content_tokens(claim.text)
            polarity = negated(claim.text)
            placed = False
            for token_set, bucket_polarity, members in buckets:
                if polarity == bucket_polarity and _similar(
                    tokens, token_set, self._threshold, self._min_tokens
                ):
                    members.append(claim)
                    token_set |= tokens  # let the cluster vocabulary grow
                    placed = True
                    break
            if not placed:
                buckets.append((set(tokens), polarity, [claim]))
        return [members for _tokens, _polarity, members in buckets]


def content_tokens(text: str) -> set[str]:
    """Content words of a claim (used for similarity and contradiction checks)."""
    return {
        t for t in _TOKEN_RE.findall(text.lower())
        if len(t) >= 3 and t not in _STOPWORDS
    }


def negated(text: str) -> bool:
    """Whether a claim contains a polarity-flipping negation word."""
    return bool(set(_TOKEN_RE.findall(text.lower())) & _NEGATIONS)


def _similar(a: set[str], b: set[str], threshold: float, min_tokens: int) -> bool:
    if not a or not b:
        return False
    inter = a & b
    if len(inter) < min_tokens:
        return False
    union = a | b
    return len(inter) / len(union) >= threshold
