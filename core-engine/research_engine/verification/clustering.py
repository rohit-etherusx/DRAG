"""Claim clustering.

Groups equivalent claims — the same assertion made in different words by
different sources — so verification can compare *claims against claims*, never
documents. Clustering is deterministic and self-contained: no model calls, no
external corpora, identical inputs always produce identical clusters.

Similarity is **rarity-weighted token Jaccard**. Plain unweighted Jaccard
(v0.4) systematically failed on real extracted claims: ubiquitous topic words
("transformer", "attention") counted as much as genuinely distinctive ones, so
unrelated claims about the same topic looked as similar as true paraphrases —
live runs corroborated ~0% of claims while the highest-scoring pairs were
false matches. Instead, every token is weighted by its rarity across the run's
claim set (an IDF computed from the claims themselves), and similarity is the
weighted Jaccard: shared-token weight over union-token weight. Distinctive
words dominate the decision; generic topic words barely count.

Two guards keep automatic clustering conservative (a false merge *fabricates
corroboration*, which is strictly worse than a missed merge):

* **polarity** — claims with different negation polarity never cluster;
  "X is effective" and "X is not effective" are a contradiction;
* **numeric conflict** — claims asserting different numbers ("28.4 BLEU" vs
  "41.8 BLEU") never cluster, however similar their wording.

Automatic merging therefore only captures near-identical wordings. Genuine
cross-source paraphrases usually land *below* the automatic threshold, in the
borderline band — :meth:`ClaimClusterer.borderline_pairs` exposes that band so
the verification engine can submit it to a semantic equivalence judge
(``verification/equivalence.py``). Without a judge the borderline band is
simply not merged, keeping offline runs deterministic.

Exact-duplicate wordings have already been merged by the claim normalizer.
"""
from __future__ import annotations

import math
import re

from research_engine.domain.models import Claim

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9'\-]+")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
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
    """Clusters equivalent claims (deterministic rarity-weighted similarity)."""

    def __init__(
        self,
        similarity_threshold: float = 0.6,
        min_shared_tokens: int = 3,
        borderline_threshold: float = 0.22,
    ) -> None:
        self._threshold = similarity_threshold
        self._min_shared = min_shared_tokens
        self._borderline = borderline_threshold

    def cluster(self, claims: list[Claim]) -> list[list[Claim]]:
        """Group ``claims`` into equivalence clusters, in first-seen order.

        Each cluster is anchored to its first-seen member (the seed): a claim
        joins the first cluster whose *seed* it matches. Comparing against the
        seed — not the cluster's growing vocabulary — prevents chained merges
        of claims that are each similar to a neighbour but not to each other.
        """
        tokens = [content_tokens(claim.text) for claim in claims]
        polarity = [negated(claim.text) for claim in claims]
        numbers = [_numbers(claim.text) for claim in claims]
        weights = token_weights(tokens)

        seeds: list[int] = []
        clusters: list[list[Claim]] = []
        for index, claim in enumerate(claims):
            placed = False
            for position, seed in enumerate(seeds):
                if polarity[index] != polarity[seed]:
                    continue
                if _numbers_conflict(numbers[index], numbers[seed]):
                    continue
                score = _weighted_jaccard(
                    tokens[index], tokens[seed], weights, self._min_shared
                )
                if score >= self._threshold:
                    clusters[position].append(claim)
                    placed = True
                    break
            if not placed:
                seeds.append(index)
                clusters.append([claim])
        return clusters

    def borderline_pairs(
        self, clusters: list[list[Claim]], limit: int
    ) -> list[tuple[int, int]]:
        """Cluster pairs too similar to dismiss but not similar enough to merge.

        Compares cluster seeds (first members) pairwise and returns the index
        pairs whose similarity falls in ``[borderline_threshold,
        similarity_threshold)`` — with the polarity and numeric-conflict guards
        still applied — ranked by similarity, capped at ``limit``. These are
        the candidates worth submitting to a semantic equivalence judge.
        """
        seeds = [members[0] for members in clusters]
        tokens = [content_tokens(claim.text) for claim in seeds]
        polarity = [negated(claim.text) for claim in seeds]
        numbers = [_numbers(claim.text) for claim in seeds]
        weights = token_weights(tokens)

        scored: list[tuple[float, int, int]] = []
        for i in range(len(seeds)):
            for j in range(i + 1, len(seeds)):
                if polarity[i] != polarity[j]:
                    continue
                if _numbers_conflict(numbers[i], numbers[j]):
                    continue
                score = _weighted_jaccard(
                    tokens[i], tokens[j], weights, self._min_shared
                )
                if self._borderline <= score < self._threshold:
                    scored.append((score, i, j))
        scored.sort(key=lambda item: (-item[0], item[1], item[2]))
        return [(i, j) for _score, i, j in scored[:limit]]


def content_tokens(text: str) -> set[str]:
    """Content words of a claim (used for similarity and contradiction checks)."""
    return {
        t for t in _TOKEN_RE.findall(text.lower())
        if len(t) >= 3 and t not in _STOPWORDS
    }


def negated(text: str) -> bool:
    """Whether a claim contains a polarity-flipping negation word."""
    return bool(set(_TOKEN_RE.findall(text.lower())) & _NEGATIONS)


def token_weights(token_sets: list[set[str]]) -> dict[str, float]:
    """Rarity weight for every token across the run's claims.

    ``log(1 + N/df)`` — a smoothed inverse document frequency over the claim
    set itself: a token appearing in every claim still carries a small positive
    weight (so tiny claim sets remain comparable), while a token unique to one
    or two claims carries several times more. Deterministic and self-contained;
    no external corpus.
    """
    total = len(token_sets) or 1
    frequency: dict[str, int] = {}
    for tokens in token_sets:
        for token in tokens:
            frequency[token] = frequency.get(token, 0) + 1
    return {
        token: math.log(1.0 + total / df) for token, df in frequency.items()
    }


def _weighted_jaccard(
    a: set[str], b: set[str], weights: dict[str, float], min_shared: int
) -> float:
    """Rarity-weighted Jaccard similarity of two token sets (0 when trivial)."""
    shared = a & b
    if len(shared) < min_shared:
        return 0.0
    union_weight = sum(weights[t] for t in a | b)
    if union_weight <= 0.0:
        return 0.0
    return sum(weights[t] for t in shared) / union_weight


def _numbers(text: str) -> frozenset[str]:
    return frozenset(_NUMBER_RE.findall(text))


def _numbers_conflict(a: frozenset[str], b: frozenset[str]) -> bool:
    """Whether two claims assert genuinely different numbers.

    Compatible when either claim has no numbers, or one claim's numbers are a
    subset of the other's (the longer claim adds detail, it doesn't disagree).
    """
    if not a or not b:
        return False
    return not (a <= b or b <= a)
