import unittest

from tests import _path  # noqa: F401

from research_engine.domain.models import ClaimType
from research_engine.reasoning.confidence import (
    ConfidenceInputs,
    ConfidenceModel,
    claim_specificity,
)


class ConfidenceModelTests(unittest.TestCase):
    def setUp(self):
        self.model = ConfidenceModel()

    def test_deterministic_and_reproducible(self):
        inputs = ConfidenceInputs(
            supporting_sources=2, independent_domains=2, mean_authority=0.8,
            agreement=0.5, contradictions=0, coverage=0.7,
            evidence_quality=0.7, specificity=0.6,
        )
        self.assertEqual(self.model.score(inputs), self.model.score(inputs))

    def test_known_weighting_with_coverage(self):
        # sources=2/3, domains=2/3, authority=.8, agreement=.5, coverage=1.0,
        # quality=.7, specificity=.6
        # base = .20*.6667 + .15*.6667 + .15*.8 + .15*.5 + .15*1.0 + .10*.7 + .10*.6
        #      = .13333 + .1 + .12 + .075 + .15 + .07 + .06 = .70833
        inputs = ConfidenceInputs(
            supporting_sources=2, independent_domains=2, mean_authority=0.8,
            agreement=0.5, contradictions=0, coverage=1.0,
            evidence_quality=0.7, specificity=0.6,
        )
        self.assertAlmostEqual(self.model.score(inputs), 0.7083, places=3)

    def test_coverage_none_renormalizes_weights(self):
        # Same factor values with and without coverage=1.0: without coverage the
        # weights renormalize, so a perfect-coverage score differs from the
        # claim-level (no-coverage) score.
        with_coverage = ConfidenceInputs(
            supporting_sources=3, independent_domains=3, mean_authority=0.6,
            agreement=0.6, coverage=0.0, evidence_quality=0.6, specificity=0.6,
        )
        without = ConfidenceInputs(
            supporting_sources=3, independent_domains=3, mean_authority=0.6,
            agreement=0.6, coverage=None, evidence_quality=0.6, specificity=0.6,
        )
        # Zero coverage drags the score down; renormalized absence does not.
        self.assertLess(self.model.score(with_coverage), self.model.score(without))

    def test_more_sources_increase_confidence(self):
        low = ConfidenceInputs(supporting_sources=1, evidence_quality=0.5)
        high = ConfidenceInputs(supporting_sources=3, evidence_quality=0.5)
        self.assertGreater(self.model.score(high), self.model.score(low))

    def test_contradictions_reduce_confidence(self):
        clean = ConfidenceInputs(
            supporting_sources=3, independent_domains=3, mean_authority=0.9,
            agreement=1.0, coverage=1.0, evidence_quality=1.0, specificity=1.0,
        )
        conflicted = ConfidenceInputs(
            supporting_sources=3, independent_domains=3, mean_authority=0.9,
            agreement=1.0, coverage=1.0, evidence_quality=1.0, specificity=1.0,
            contradictions=2,
        )
        self.assertLess(self.model.score(conflicted), self.model.score(clean))

    def test_never_certain(self):
        maxed = ConfidenceInputs(
            supporting_sources=99, independent_domains=99, mean_authority=1.0,
            agreement=1.0, coverage=1.0, evidence_quality=1.0, specificity=1.0,
        )
        self.assertLessEqual(self.model.score(maxed), 0.95)

    def test_empty_inputs_zero(self):
        self.assertEqual(self.model.score(ConfidenceInputs()), 0.0)

    def test_report_carries_factors_and_explanation(self):
        inputs = ConfidenceInputs(
            supporting_sources=4, independent_domains=3, mean_authority=0.82,
            agreement=0.91, contradictions=1, coverage=0.76,
            evidence_quality=0.7, specificity=0.5,
        )
        report = self.model.report(inputs)
        self.assertEqual(report.independent_sources, 4)
        self.assertEqual(report.contradictions, 1)
        self.assertAlmostEqual(report.coverage, 0.76)
        self.assertEqual(report.score, self.model.score(inputs))
        # The explanation names the factors and the score.
        self.assertIn("4 independent source(s)", report.explanation)
        self.assertIn("agreement 91%", report.explanation)
        self.assertIn("contradiction", report.explanation)
        self.assertIn(f"{report.score:.0%}", report.explanation)

    def test_specificity_by_claim_type(self):
        self.assertGreater(
            claim_specificity(ClaimType.NUMERICAL),
            claim_specificity(ClaimType.FACT),
        )
        self.assertLess(
            claim_specificity(ClaimType.OPEN_QUESTION),
            claim_specificity(ClaimType.FACT),
        )


if __name__ == "__main__":
    unittest.main()
