import unittest

from tests import _path  # noqa: F401

from research_engine.domain.models import (
    Claim,
    ClaimType,
    Source,
    VerificationStatus,
)
from research_engine.verification.clustering import ClaimClusterer
from research_engine.verification.verifier import ClaimVerifier


def _claim(cid, text, source_ids, evidence_ids=None, claim_type=ClaimType.FACT):
    return Claim(
        id=cid,
        text=text,
        claim_type=claim_type,
        evidence_ids=evidence_ids or [f"ev-{cid}"],
        source_ids=list(source_ids),
        subquestion_ids=["sq-1"],
    )


def _sources(domains):
    return {
        f"src-{i}": Source(
            id=f"src-{i}", title="t", provider="p", domain=domain,
        )
        for i, domain in enumerate(domains, start=1)
    }


class ClaimClustererTests(unittest.TestCase):
    def test_similar_claims_cluster_together(self):
        clusterer = ClaimClusterer()
        claims = [
            _claim("c1", "Quantum computers threaten RSA encryption security.", ["src-1"]),
            _claim("c2", "RSA encryption security is threatened by quantum computers.", ["src-2"]),
            _claim("c3", "Wind turbines require regular blade maintenance.", ["src-3"]),
        ]
        clusters = clusterer.cluster(claims)
        self.assertEqual(len(clusters), 2)
        self.assertEqual(len(clusters[0]), 2)

    def test_short_claims_do_not_cluster_spuriously(self):
        clusterer = ClaimClusterer()
        claims = [
            _claim("c1", "It works.", ["src-1"]),
            _claim("c2", "It fails.", ["src-2"]),
        ]
        self.assertEqual(len(clusterer.cluster(claims)), 2)


class ClaimVerifierTests(unittest.TestCase):
    def test_corroborated_claim_across_independent_domains(self):
        sources = _sources(["a.org", "b.com"])
        claims = [
            _claim("c1", "Quantum computers threaten RSA encryption security.", ["src-1"]),
            _claim("c2", "RSA encryption security is threatened by quantum computers.", ["src-2"]),
        ]
        result = ClaimVerifier().verify(claims, sources)
        self.assertEqual(len(result.claims), 1)
        claim = result.claims[0]
        self.assertEqual(claim.id, "claim-1")  # ids reassigned contiguously
        self.assertEqual(claim.supporting_sources, 2)
        self.assertEqual(claim.independent_domains, 2)
        self.assertGreater(claim.agreement, 0.0)
        self.assertEqual(claim.status, VerificationStatus.CORROBORATED)
        # Merged provenance from both members.
        self.assertEqual(set(claim.source_ids), {"src-1", "src-2"})
        self.assertEqual(result.corroborated_claims, 1)

    def test_single_source_claim_is_flagged_unsupported(self):
        sources = _sources(["a.org"])
        claims = [_claim("c1", "Solar adoption is accelerating rapidly.", ["src-1"])]
        result = ClaimVerifier().verify(claims, sources)
        self.assertEqual(result.claims[0].status, VerificationStatus.SINGLE_SOURCE)
        self.assertEqual(result.claims[0].agreement, 0.0)
        self.assertEqual(result.unsupported_claims, 1)

    def test_contradictions_are_detected_and_linked(self):
        sources = _sources(["a.org", "b.com"])
        claims = [
            _claim("c1", "The vaccine is effective against severe disease.", ["src-1"]),
            _claim("c2", "The vaccine is not effective against severe disease.", ["src-2"]),
        ]
        result = ClaimVerifier().verify(claims, sources)
        self.assertEqual(len(result.contradictions), 1)
        first, second = result.claims
        self.assertEqual(first.status, VerificationStatus.CONTRADICTED)
        self.assertEqual(second.status, VerificationStatus.CONTRADICTED)
        self.assertIn(second.id, first.contradicts)
        self.assertIn(first.id, second.contradicts)
        self.assertEqual(
            set(result.contradictions[0].claim_ids), {first.id, second.id}
        )

    def test_agreement_rewards_domain_diversity(self):
        same_domain = _sources(["a.org", "a.org"])
        claims = [
            _claim("c1", "Quantum computers threaten RSA encryption security.", ["src-1"]),
            _claim("c2", "RSA encryption security is threatened by quantum computers.", ["src-2"]),
        ]
        low = ClaimVerifier().verify(claims, same_domain).claims[0].agreement

        diverse = _sources(["a.org", "b.com"])
        claims2 = [
            _claim("c1", "Quantum computers threaten RSA encryption security.", ["src-1"]),
            _claim("c2", "RSA encryption security is threatened by quantum computers.", ["src-2"]),
        ]
        high = ClaimVerifier().verify(claims2, diverse).claims[0].agreement
        self.assertGreater(high, low)

    def test_verification_is_deterministic(self):
        sources = _sources(["a.org", "b.com"])

        def run():
            claims = [
                _claim("c1", "Quantum computers threaten RSA encryption security.", ["src-1"]),
                _claim("c2", "RSA encryption security is threatened by quantum computers.", ["src-2"]),
                _claim("c3", "Wind turbines require regular blade maintenance.", ["src-1"]),
            ]
            result = ClaimVerifier().verify(claims, sources)
            return [(c.id, c.text, c.agreement, c.status) for c in result.claims]

        self.assertEqual(run(), run())


if __name__ == "__main__":
    unittest.main()
