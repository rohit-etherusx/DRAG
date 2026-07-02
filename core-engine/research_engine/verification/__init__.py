"""Evidence verification (v0.3).

Extraction produces claims one source at a time, so the same fact asserted by
three independent sources arrives as three separate, unconnected evidence items.
This package restores that structure: it clusters equivalent claims and measures
*agreement* — how many independent sources and domains corroborate each claim.
Agreement is a primary input to deterministic confidence estimation.
"""
from research_engine.verification.clustering import ClaimClusterer
from research_engine.verification.verifier import EvidenceVerifier, VerificationResult

__all__ = ["ClaimClusterer", "EvidenceVerifier", "VerificationResult"]
