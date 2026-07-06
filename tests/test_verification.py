import unittest

from tests import _path  # noqa: F401

from research_engine.domain.models import (
    Claim,
    ClaimType,
    Source,
    VerificationStatus,
)
from research_engine.verification.clustering import ClaimClusterer
from research_engine.verification.equivalence import (
    ClaimEquivalenceJudge,
    LLMEquivalenceJudge,
)
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

    def test_conflicting_numbers_never_cluster(self):
        clusterer = ClaimClusterer()
        claims = [
            _claim("c1", "The Transformer achieved 28.4 BLEU on the WMT "
                         "translation benchmark task.", ["src-1"]),
            _claim("c2", "The Transformer achieved 41.8 BLEU on the WMT "
                         "translation benchmark task.", ["src-2"]),
        ]
        self.assertEqual(len(clusterer.cluster(claims)), 2)

    def test_generic_topic_overlap_does_not_cluster(self):
        # Both claims are about transformers/attention but assert different
        # facts; rarity weighting keeps shared topic words from merging them.
        clusterer = ClaimClusterer()
        claims = [
            _claim("c1", "In 2017 researchers introduced the Transformer "
                         "architecture in a landmark attention paper.",
                   ["src-1"]),
            _claim("c2", "The multi-head attention mechanism is a key "
                         "component of the Transformer architecture.",
                   ["src-2"]),
            _claim("c3", "Wind turbines require regular blade maintenance "
                         "and periodic gearbox inspection.", ["src-3"]),
        ]
        self.assertEqual(len(clusterer.cluster(claims)), 3)

    def test_borderline_pairs_expose_the_undecidable_band(self):
        clusterer = ClaimClusterer()
        claims = [
            _claim("c1", "Self-attention captures long-range dependencies "
                         "and context in input sequences.", ["src-1"]),
            _claim("c2", "The self-attention mechanism helps capture the "
                         "context of words in input sequences.", ["src-2"]),
            _claim("c3", "Wind turbines require regular blade maintenance.",
                   ["src-3"]),
        ]
        clusters = clusterer.cluster(claims)
        pairs = clusterer.borderline_pairs(clusters, limit=10)
        seeds = [(clusters[i][0].id, clusters[j][0].id) for i, j in pairs]
        self.assertIn(("c1", "c2"), seeds)
        self.assertNotIn(("c1", "c3"), seeds)
        self.assertNotIn(("c2", "c3"), seeds)


class _StubJudge(ClaimEquivalenceJudge):
    """Accepts exactly the pairs whose texts are registered as equivalent."""

    def __init__(self, equivalent_texts):
        self._equivalent = {frozenset(pair) for pair in equivalent_texts}
        self.seen = []

    def equivalent(self, pairs):
        self.seen.extend(pairs)
        return [
            frozenset((a.text, b.text)) in self._equivalent for a, b in pairs
        ]


class _StubLLM:
    name = "stub"

    def __init__(self, responses):
        self._responses = list(responses)

    @property
    def available(self):
        return True

    def generate(self, prompt, system=None, *, json_object=False):
        return self._responses.pop(0) if self._responses else None


class EquivalenceJudgeTests(unittest.TestCase):
    _PARAPHRASES = [
        "Self-attention captures long-range dependencies and context in "
        "input sequences.",
        "The self-attention mechanism helps capture the context of words "
        "in input sequences.",
    ]

    def test_judge_merges_borderline_paraphrases_into_corroboration(self):
        sources = _sources(["a.org", "b.com"])
        claims = [
            _claim("c1", self._PARAPHRASES[0], ["src-1"]),
            _claim("c2", self._PARAPHRASES[1], ["src-2"]),
        ]
        judge = _StubJudge([tuple(self._PARAPHRASES)])
        result = ClaimVerifier(judge=judge).verify(claims, sources)
        self.assertEqual(len(result.claims), 1)
        self.assertEqual(result.claims[0].supporting_sources, 2)
        self.assertEqual(
            result.claims[0].status, VerificationStatus.CORROBORATED
        )

    def test_rejected_verdicts_change_nothing(self):
        sources = _sources(["a.org", "b.com"])
        claims = [
            _claim("c1", self._PARAPHRASES[0], ["src-1"]),
            _claim("c2", self._PARAPHRASES[1], ["src-2"]),
        ]
        judge = _StubJudge([])  # judge refutes every pair
        result = ClaimVerifier(judge=judge).verify(claims, sources)
        self.assertEqual(len(result.claims), 2)
        self.assertTrue(judge.seen)  # the borderline pair was submitted

    def test_llm_judge_parses_strict_json_and_fails_closed(self):
        claims = [
            _claim("c1", self._PARAPHRASES[0], ["src-1"]),
            _claim("c2", self._PARAPHRASES[1], ["src-2"]),
        ]
        pair = [(claims[0], claims[1])]
        accepted = LLMEquivalenceJudge(_StubLLM(['{"equivalent": [0]}']))
        self.assertEqual(accepted.equivalent(pair), [True])
        # Unusable output (twice) degrades to "not equivalent".
        broken = LLMEquivalenceJudge(_StubLLM(["not json", "still not"]))
        self.assertEqual(broken.equivalent(pair), [False])
        # Out-of-range indices are ignored rather than crashing.
        wild = LLMEquivalenceJudge(_StubLLM(['{"equivalent": [7]}']))
        self.assertEqual(wild.equivalent(pair), [False])


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
