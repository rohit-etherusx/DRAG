"""Evidence verifier.

Coordinates verification: it clusters equivalent claims and packages the result
with lookups the reasoning/confidence stages need (e.g. the cluster a given
evidence item belongs to, and how many claims are corroborated by more than one
source). Kept thin and deterministic so confidence stays reproducible.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from research_engine.domain.models import ClaimCluster, Evidence, Source
from research_engine.verification.clustering import ClaimClusterer


@dataclass
class VerificationResult:
    """Clusters plus convenience lookups over them."""

    clusters: list[ClaimCluster] = field(default_factory=list)
    #: evidence_id -> the cluster containing it.
    _by_evidence: dict[str, ClaimCluster] = field(default_factory=dict)

    def cluster_for(self, evidence_id: str) -> ClaimCluster | None:
        return self._by_evidence.get(evidence_id)

    @property
    def corroborated_clusters(self) -> int:
        """Clusters asserted by two or more independent sources."""
        return sum(1 for c in self.clusters if c.supporting_sources >= 2)

    def agreement_for(self, evidence_id: str) -> float:
        cluster = self._by_evidence.get(evidence_id)
        return cluster.agreement if cluster else 0.0


class EvidenceVerifier:
    """Produces claim clusters and agreement metrics from evidence."""

    def __init__(self, clusterer: ClaimClusterer | None = None) -> None:
        self._clusterer = clusterer or ClaimClusterer()

    def verify(
        self, evidence: list[Evidence], sources: dict[str, Source]
    ) -> VerificationResult:
        clusters = self._clusterer.cluster(evidence, sources)
        by_evidence: dict[str, ClaimCluster] = {}
        for cluster in clusters:
            for evidence_id in cluster.evidence_ids:
                by_evidence[evidence_id] = cluster
        return VerificationResult(clusters=clusters, _by_evidence=by_evidence)
