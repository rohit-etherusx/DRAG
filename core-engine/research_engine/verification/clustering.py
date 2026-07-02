"""Claim clustering.

Groups equivalent claims — the same assertion made by different sources — into
:class:`~research_engine.domain.models.ClaimCluster` objects. Clustering is
deterministic: two claims are considered equivalent when their content-word sets
are sufficiently similar (Jaccard overlap above a threshold). This is
domain-agnostic and reproducible; an LLM-based semantic clusterer could be
substituted behind the same method signature later without changing callers.

Each cluster records how many distinct sources and distinct network domains
assert the claim, and an ``agreement`` strength derived from that corroboration.
"""
from __future__ import annotations

import re

from research_engine.domain.models import ClaimCluster, Evidence, Source

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9'\-]+")
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "as",
    "by", "at", "from", "is", "are", "was", "were", "be", "been", "being", "this",
    "that", "these", "those", "it", "its", "into", "also", "such", "which", "can",
    "may", "has", "have", "had", "not", "but", "than", "then", "there",
}


class ClaimClusterer:
    """Clusters equivalent claims across evidence items (deterministic)."""

    def __init__(self, similarity_threshold: float = 0.6, min_tokens: int = 3) -> None:
        self._threshold = similarity_threshold
        self._min_tokens = min_tokens

    def cluster(
        self, evidence: list[Evidence], sources: dict[str, Source]
    ) -> list[ClaimCluster]:
        """Group ``evidence`` into equivalent-claim clusters.

        ``sources`` maps ``source_id`` → :class:`Source`, used to count
        independent domains. Order is stable: clusters follow first-seen order.
        """
        # (token_set, [evidence]) accumulators, in first-seen order.
        buckets: list[tuple[set[str], list[Evidence]]] = []
        for item in evidence:
            tokens = _content_tokens(item.claim)
            placed = False
            for token_set, members in buckets:
                if _similar(tokens, token_set, self._threshold, self._min_tokens):
                    members.append(item)
                    token_set |= tokens  # let the cluster vocabulary grow
                    placed = True
                    break
            if not placed:
                buckets.append((set(tokens), [item]))

        clusters: list[ClaimCluster] = []
        for index, (_tokens, members) in enumerate(buckets, start=1):
            source_ids = _distinct([m.source_id for m in members])
            domains = _distinct(
                d for d in (
                    _domain_for(sid, sources) for sid in source_ids
                ) if d
            )
            supporting = len(source_ids)
            independent_domains = len(domains)
            clusters.append(
                ClaimCluster(
                    id=f"cluster-{index}",
                    canonical_claim=_canonical(members),
                    evidence_ids=[m.id for m in members],
                    source_ids=source_ids,
                    supporting_sources=supporting,
                    independent_domains=independent_domains,
                    agreement=_agreement(supporting, independent_domains),
                )
            )
        return clusters


def _content_tokens(claim: str) -> set[str]:
    return {
        t for t in _TOKEN_RE.findall(claim.lower())
        if len(t) >= 3 and t not in _STOPWORDS
    }


def _similar(a: set[str], b: set[str], threshold: float, min_tokens: int) -> bool:
    if not a or not b:
        return False
    inter = a & b
    if len(inter) < min_tokens:
        return False
    union = a | b
    return len(inter) / len(union) >= threshold


def _canonical(members: list[Evidence]) -> str:
    """Pick a representative claim — the longest, as a stable proxy for detail."""
    return max(members, key=lambda e: (len(e.claim), e.id)).claim


def _agreement(supporting_sources: int, independent_domains: int) -> float:
    """Corroboration strength in 0..1.

    Rises with the number of independent sources; a small bonus rewards diversity
    across distinct domains (independent corroboration is stronger than repeated
    assertion within one domain). One source → 0.0 (uncorroborated).
    """
    if supporting_sources <= 1:
        base = 0.0
    else:
        base = min(1.0, (supporting_sources - 1) / 3.0)
    if independent_domains >= 2:
        base = min(1.0, base + 0.15 * (independent_domains - 1))
    return round(base, 4)


def _domain_for(source_id: str, sources: dict[str, Source]) -> str:
    source = sources.get(source_id)
    return source.domain if source else ""


def _distinct(items) -> list[str]:
    """Distinct values, preserving first-seen order."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out
