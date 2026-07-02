"""Claim verification.

Extraction produces claims one source at a time, so the same fact asserted by
three independent sources arrives as three separate claims. This package
restores that structure: it clusters equivalent claims, merges each cluster
into one canonical claim, measures *agreement* (independent corroboration
across sources and domains), detects contradictions between claims, and flags
unsupported single-source claims. Verification compares claims, never
documents, and every claim leaves with verification metadata stamped on it.
"""
from research_engine.verification.clustering import ClaimClusterer
from research_engine.verification.verifier import ClaimVerifier, VerificationResult

__all__ = ["ClaimClusterer", "ClaimVerifier", "VerificationResult"]
