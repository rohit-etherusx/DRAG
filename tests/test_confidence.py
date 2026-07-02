import unittest

from tests import _path  # noqa: F401

from research_engine.domain.models import ClaimCluster, Evidence, Source
from research_engine.reasoning.confidence import ConfidenceInputs, ConfidenceModel
from research_engine.verification.verifier import EvidenceVerifier


class ConfidenceModelTests(unittest.TestCase):
    def setUp(self):
        self.model = ConfidenceModel()

    def test_deterministic_and_reproducible(self):
        inputs = ConfidenceInputs(
            supporting_sources=2, independent_domains=2, mean_authority=0.8,
            agreement=0.5, contradictions=0, mean_relevance=0.7,
        )
        self.assertEqual(self.model.score(inputs), self.model.score(inputs))

    def test_known_weighting(self):
        # source=2/3, domain=2/3, authority=0.8, agreement=0.5, relevance=0.7
        # base = .30*.6667 + .20*.6667 + .20*.8 + .15*.5 + .15*.7
        #      = .2 + .1333 + .16 + .075 + .105 = .6733...
        inputs = ConfidenceInputs(
            supporting_sources=2, independent_domains=2, mean_authority=0.8,
            agreement=0.5, contradictions=0, mean_relevance=0.7,
        )
        self.assertAlmostEqual(self.model.score(inputs), 0.6733, places=3)

    def test_more_sources_increase_confidence(self):
        low = ConfidenceInputs(supporting_sources=1, mean_relevance=0.5)
        high = ConfidenceInputs(supporting_sources=3, mean_relevance=0.5)
        self.assertGreater(self.model.score(high), self.model.score(low))

    def test_contradictions_reduce_confidence(self):
        clean = ConfidenceInputs(
            supporting_sources=3, independent_domains=3, mean_authority=0.9,
            agreement=1.0, mean_relevance=1.0, contradictions=0,
        )
        conflicted = ConfidenceInputs(
            supporting_sources=3, independent_domains=3, mean_authority=0.9,
            agreement=1.0, mean_relevance=1.0, contradictions=2,
        )
        self.assertLess(self.model.score(conflicted), self.model.score(clean))

    def test_never_certain(self):
        maxed = ConfidenceInputs(
            supporting_sources=99, independent_domains=99, mean_authority=1.0,
            agreement=1.0, mean_relevance=1.0, contradictions=0,
        )
        self.assertLessEqual(self.model.score(maxed), 0.95)

    def test_empty_inputs_zero(self):
        self.assertEqual(self.model.score(ConfidenceInputs()), 0.0)

    def test_breakdown_includes_confidence(self):
        b = self.model.breakdown(ConfidenceInputs(supporting_sources=2, mean_relevance=0.5))
        self.assertIn("confidence", b)
        self.assertIn("supporting_sources", b)


class VerificationIntegrationTests(unittest.TestCase):
    """Clustering + verifier feed agreement into confidence-relevant metrics."""

    def _sources(self):
        return {
            "src-1": Source(id="src-1", title="a", provider="wikipedia", domain="wikipedia.org"),
            "src-2": Source(id="src-2", title="b", provider="arxiv", domain="arxiv.org"),
        }

    def test_equivalent_claims_cluster_and_corroborate(self):
        evidence = [
            Evidence(id="ev-1", claim="Photosynthesis converts sunlight into chemical energy.",
                     source_id="src-1", task_id="t"),
            Evidence(id="ev-2", claim="Photosynthesis converts sunlight into chemical energy in plants.",
                     source_id="src-2", task_id="t"),
            Evidence(id="ev-3", claim="Mitochondria are the powerhouse of the cell.",
                     source_id="src-1", task_id="t"),
        ]
        result = EvidenceVerifier().verify(evidence, self._sources())
        # The two photosynthesis claims cluster; the mitochondria claim stands alone.
        corroborated = [c for c in result.clusters if c.supporting_sources >= 2]
        self.assertEqual(len(corroborated), 1)
        cluster = corroborated[0]
        self.assertEqual(cluster.supporting_sources, 2)
        self.assertEqual(cluster.independent_domains, 2)
        self.assertGreater(cluster.agreement, 0.0)
        self.assertGreater(result.agreement_for("ev-1"), 0.0)
        self.assertEqual(result.agreement_for("ev-3"), 0.0)

    def test_single_source_no_agreement(self):
        evidence = [
            Evidence(id="ev-1", claim="A unique standalone claim about something.",
                     source_id="src-1", task_id="t"),
        ]
        result = EvidenceVerifier().verify(evidence, self._sources())
        self.assertEqual(len(result.clusters), 1)
        self.assertEqual(result.clusters[0].agreement, 0.0)
        self.assertEqual(result.corroborated_clusters, 0)


if __name__ == "__main__":
    unittest.main()
