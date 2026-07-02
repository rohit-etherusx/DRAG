"""Claim verification engine.

Verification compares claims — never documents (``OBJECTIVE.md`` module 7).
Given the normalized claims and the sources behind them, the engine:

* clusters equivalent claims across sources and merges each cluster into one
  canonical claim (evidence, sources, entities, and wordings unioned) — the
  deterministic clusterer auto-merges near-identical wordings, and an optional
  semantic equivalence judge reviews the borderline band the clusterer cannot
  decide lexically (``verification/equivalence.py``);
* measures **agreement**: how many distinct sources — and, more importantly,
  distinct network domains — independently assert each claim;
* detects **disagreement**: pairs of claims that share vocabulary but differ on
  negation are flagged as contradictions, linked from both claims;
* flags **unsupported** claims: assertions no independent source corroborates.

Every claim leaves this stage with verification metadata stamped on it
(``supporting_sources``, ``independent_domains``, ``agreement``,
``contradicts``, ``status``), so downstream reasoning never needs to look
behind the claims. Without a judge the stage is fully deterministic; with one,
the judge can only *add* merges the deterministic path missed.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from research_engine.domain.models import (
    Claim,
    ClaimType,
    Contradiction,
    Source,
    VerificationStatus,
)
from research_engine.logging_setup import get_logger
from research_engine.verification.clustering import (
    ClaimClusterer,
    content_tokens,
    negated,
)
from research_engine.verification.equivalence import ClaimEquivalenceJudge

_log = get_logger("verification.verifier")


@dataclass
class VerificationResult:
    """Verified canonical claims plus the contradictions found between them."""

    claims: list[Claim] = field(default_factory=list)
    contradictions: list[Contradiction] = field(default_factory=list)

    @property
    def corroborated_claims(self) -> int:
        """Claims asserted by two or more distinct sources."""
        return sum(1 for c in self.claims if c.supporting_sources >= 2)

    @property
    def unsupported_claims(self) -> int:
        """Claims no independent source corroborates."""
        return sum(
            1 for c in self.claims if c.status is VerificationStatus.SINGLE_SOURCE
        )


class ClaimVerifier:
    """Produces verified canonical claims from normalized claims."""

    def __init__(
        self,
        clusterer: ClaimClusterer | None = None,
        judge: ClaimEquivalenceJudge | None = None,
        max_equivalence_checks: int = 40,
    ) -> None:
        self._clusterer = clusterer or ClaimClusterer()
        self._judge = judge
        self._max_checks = max(0, max_equivalence_checks)

    def verify(
        self, claims: list[Claim], sources: dict[str, Source]
    ) -> VerificationResult:
        clusters = self._clusterer.cluster(claims)
        if self._judge is not None and self._max_checks:
            clusters = self._judged_merge(clusters)
        verified = [_merge_cluster(members) for members in clusters]
        for index, claim in enumerate(verified, start=1):
            claim.id = f"claim-{index}"
            self._stamp_agreement(claim, sources)

        contradictions = _detect_contradictions(verified)
        for claim in verified:
            claim.status = _status(claim)
        return VerificationResult(claims=verified, contradictions=contradictions)

    def _judged_merge(
        self, clusters: list[list[Claim]]
    ) -> list[list[Claim]]:
        """Merge clusters whose borderline pairs the equivalence judge accepts.

        The judge only sees pairs the deterministic clusterer found borderline
        (guards already applied); accepted verdicts are combined with
        union-find so transitive equivalences collapse into one cluster while
        first-seen ordering is preserved.
        """
        pairs = self._clusterer.borderline_pairs(clusters, self._max_checks)
        if not pairs:
            return clusters
        seed_pairs = [(clusters[i][0], clusters[j][0]) for i, j in pairs]
        verdicts = self._judge.equivalent(seed_pairs)
        accepted = [pair for pair, verdict in zip(pairs, verdicts) if verdict]
        if not accepted:
            return clusters
        _log.info(
            "Equivalence judge merged %d of %d borderline claim pair(s)",
            len(accepted),
            len(pairs),
        )

        parent = list(range(len(clusters)))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for i, j in accepted:
            root_i, root_j = find(i), find(j)
            if root_i != root_j:  # attach the later cluster to the earlier one
                parent[max(root_i, root_j)] = min(root_i, root_j)

        merged: dict[int, list[Claim]] = {}
        order: list[int] = []
        for index, members in enumerate(clusters):
            root = find(index)
            if root not in merged:
                merged[root] = []
                order.append(root)
            merged[root].extend(members)
        return [merged[root] for root in order]

    @staticmethod
    def _stamp_agreement(claim: Claim, sources: dict[str, Source]) -> None:
        domains = {
            sources[sid].domain
            for sid in claim.source_ids
            if sid in sources and sources[sid].domain
        }
        claim.supporting_sources = len(claim.source_ids)
        claim.independent_domains = len(domains)
        claim.agreement = _agreement(claim.supporting_sources, len(domains))


def _merge_cluster(members: list[Claim]) -> Claim:
    """Collapse a cluster of equivalent claims into one canonical claim."""
    canonical = max(members, key=lambda c: (len(c.text), c.id))
    merged = members[0]  # first-seen member keeps ordering stable
    if merged is not canonical:
        if merged.text not in merged.variants:
            merged.variants.append(merged.text)
        merged.text = canonical.text
    for other in members[1:]:
        _extend_unique(merged.evidence_ids, other.evidence_ids)
        _extend_unique(merged.source_ids, other.source_ids)
        _extend_unique(merged.subquestion_ids, other.subquestion_ids)
        _extend_unique(merged.entities, other.entities)
        _extend_unique(merged.variants, [other.text] + other.variants)
        if merged.claim_type is ClaimType.FACT:
            merged.claim_type = other.claim_type
    merged.variants = [v for v in merged.variants if v != merged.text]
    return merged


def _detect_contradictions(claims: list[Claim]) -> list[Contradiction]:
    """Flag claim pairs that share vocabulary but differ on negation.

    Deliberately simple and deterministic; a semantic (embedding/LLM)
    comparison remains a documented seam that can replace this without
    touching callers.
    """
    contradictions: list[Contradiction] = []
    tokens = [content_tokens(claim.text) for claim in claims]
    polarity = [negated(claim.text) for claim in claims]
    counter = 0
    for i in range(len(claims)):
        for j in range(i + 1, len(claims)):
            if polarity[i] == polarity[j]:
                continue
            words_i, words_j = tokens[i], tokens[j]
            shared = words_i & words_j
            smaller = min(len(words_i), len(words_j)) or 1
            if len(shared) / smaller >= 0.6 and len(shared) >= 3:
                counter += 1
                contradictions.append(
                    Contradiction(
                        id=f"contra-{counter}",
                        description=(
                            "Conflicting claims: "
                            f'"{claims[i].text}" vs "{claims[j].text}"'
                        ),
                        claim_ids=[claims[i].id, claims[j].id],
                    )
                )
                if claims[j].id not in claims[i].contradicts:
                    claims[i].contradicts.append(claims[j].id)
                if claims[i].id not in claims[j].contradicts:
                    claims[j].contradicts.append(claims[i].id)
    return contradictions


def _status(claim: Claim) -> VerificationStatus:
    if claim.contradicts:
        return VerificationStatus.CONTRADICTED
    if claim.supporting_sources >= 2:
        return VerificationStatus.CORROBORATED
    return VerificationStatus.SINGLE_SOURCE


def _agreement(supporting_sources: int, independent_domains: int) -> float:
    """Corroboration strength in 0..1.

    Rises with the number of independent sources; a small bonus rewards
    diversity across distinct domains (independent corroboration is stronger
    than repeated assertion within one domain). One source → 0.0.
    """
    if supporting_sources <= 1:
        base = 0.0
    else:
        base = min(1.0, (supporting_sources - 1) / 3.0)
    if independent_domains >= 2:
        base = min(1.0, base + 0.15 * (independent_domains - 1))
    return round(base, 4)


def _extend_unique(target: list[str], items: list[str]) -> None:
    for item in items:
        if item and item not in target:
            target.append(item)
