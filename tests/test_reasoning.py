import unittest

from tests import _path  # noqa: F401

from research_engine.domain.models import (
    Claim,
    ClaimType,
    Contradiction,
    Evidence,
    ResearchPlan,
    Source,
    SubQuestion,
    VerificationStatus,
)
from research_engine.knowledge.graph import EvidenceGraph
from research_engine.reasoning.analyzer import ReasoningEngine


def _plan(is_question=False, subquestions=2):
    return ResearchPlan(
        objective="Understand solar storage",
        question="How is solar energy stored?" if is_question else "Solar storage",
        is_question=is_question,
        subject="solar storage",
        subquestions=[
            SubQuestion(id=f"sq-{i}", question=f"Subquestion {i}?")
            for i in range(1, subquestions + 1)
        ],
    )


def _claim(cid, text, subquestion_ids, sources=1, claim_type=ClaimType.FACT,
           agreement=0.0, contradicts=None):
    claim = Claim(
        id=cid, text=text, claim_type=claim_type,
        evidence_ids=[f"ev-{cid}"],
        source_ids=[f"src-{i}" for i in range(1, sources + 1)],
        subquestion_ids=list(subquestion_ids),
        supporting_sources=sources,
        independent_domains=sources,
        agreement=agreement,
        contradicts=contradicts or [],
    )
    claim.status = (
        VerificationStatus.CONTRADICTED if claim.contradicts
        else VerificationStatus.CORROBORATED if sources >= 2
        else VerificationStatus.SINGLE_SOURCE
    )
    return claim


def _sources(n):
    return {
        f"src-{i}": Source(
            id=f"src-{i}", title="t", provider="p",
            domain=f"d{i}.org", authority=0.7,
        )
        for i in range(1, n + 1)
    }


def _evidence_for(claims):
    return [
        Evidence(id=f"ev-{c.id}", passage=c.text, document_id="doc-1",
                 source_id=c.source_ids[0] if c.source_ids else "src-1",
                 relevance_score=0.8)
        for c in claims
    ]


def _analyze(claims, plan, contradictions=None, sources=None):
    graph = EvidenceGraph()
    evidence = _evidence_for(claims)
    graph.build(claims, evidence)
    return ReasoningEngine().analyze(
        plan=plan,
        claims=claims,
        graph=graph,
        contradictions=contradictions or [],
        sources=sources or _sources(3),
        evidence=evidence,
    )


class FindingTests(unittest.TestCase):
    def test_findings_reference_claims_and_carry_explained_confidence(self):
        plan = _plan()
        claims = [
            _claim("claim-1", "Batteries store solar energy.", ["sq-1"],
                   sources=2, agreement=0.5),
            _claim("claim-2", "Pumped hydro also stores energy.", ["sq-2"],
                   sources=2, agreement=0.5),
        ]
        result = _analyze(claims, plan)
        self.assertEqual(len(result.findings), 2)
        finding = result.findings[0]
        self.assertEqual(finding.subquestion_id, "sq-1")
        self.assertEqual(finding.claim_ids, ["claim-1"])
        self.assertGreater(finding.confidence, 0.0)
        self.assertIn("Confidence", finding.confidence_explanation)
        # Every claim was stamped with explained confidence too.
        for claim in claims:
            self.assertGreater(claim.confidence, 0.0)
            self.assertIn("Confidence", claim.confidence_explanation)

    def test_subquestion_without_evidence_becomes_missing_evidence(self):
        plan = _plan(subquestions=2)
        claims = [
            _claim("claim-1", "Batteries store solar energy.", ["sq-1"], sources=2)
        ]
        result = _analyze(claims, plan)
        self.assertEqual(len(result.findings), 1)
        self.assertEqual(result.weak_subquestion_ids, ["sq-2"])
        self.assertTrue(
            any("Subquestion 2?" in gap for gap in result.missing_evidence)
        )

    def test_single_source_subquestion_is_weak_but_still_reported(self):
        plan = _plan(subquestions=1)
        claims = [_claim("claim-1", "Solo claim.", ["sq-1"], sources=1)]
        result = _analyze(claims, plan)
        self.assertEqual(len(result.findings), 1)
        self.assertEqual(result.weak_subquestion_ids, ["sq-1"])
        self.assertTrue(
            any("single-source" in gap for gap in result.missing_evidence)
        )


class DirectAnswerTests(unittest.TestCase):
    def test_question_plan_gets_direct_answer_from_strongest_claims(self):
        plan = _plan(is_question=True)
        claims = [
            _claim("claim-1", "Batteries store solar energy overnight.", ["sq-1"],
                   sources=3, agreement=0.8),
            _claim("claim-2", "Storage lags demand.", ["sq-2"], sources=1),
        ]
        result = _analyze(claims, plan)
        self.assertIn("Batteries store solar energy overnight.", result.direct_answer)

    def test_topic_plan_gets_no_direct_answer(self):
        plan = _plan(is_question=False)
        claims = [_claim("claim-1", "X.", ["sq-1"], sources=2)]
        result = _analyze(claims, plan)
        self.assertEqual(result.direct_answer, "")

    def test_no_usable_claims_yields_empty_answer(self):
        plan = _plan(is_question=True, subquestions=1)
        result = _analyze([], plan)
        self.assertEqual(result.direct_answer, "")
        self.assertEqual(result.findings, [])
        self.assertEqual(result.confidence.score, 0.0)


class DerivationTests(unittest.TestCase):
    def test_patterns_flag_entities_spanning_subquestions(self):
        plan = _plan(subquestions=2)
        claims = [
            _claim("claim-1", "A.", ["sq-1"], sources=2),
            _claim("claim-2", "B.", ["sq-2"], sources=2),
        ]
        claims[0].entities = ["Battery"]
        claims[1].entities = ["Battery"]
        result = _analyze(claims, plan)
        self.assertTrue(any("Battery" in p for p in result.patterns))

    def test_open_questions_from_claims_and_contradictions(self):
        plan = _plan(subquestions=1)
        claims = [
            _claim("claim-1", "What is the long-term degradation rate?",
                   ["sq-1"], claim_type=ClaimType.OPEN_QUESTION),
            _claim("claim-2", "Batteries degrade.", ["sq-1"], sources=2),
        ]
        contradiction = Contradiction(
            id="contra-1", description="X vs Y", claim_ids=["claim-2"]
        )
        result = _analyze(claims, plan, contradictions=[contradiction])
        self.assertIn(
            "What is the long-term degradation rate?", result.open_questions
        )
        self.assertTrue(any("X vs Y" in q for q in result.open_questions))

    def test_open_question_claims_do_not_become_findings(self):
        plan = _plan(subquestions=1)
        claims = [
            _claim("claim-1", "What remains unknown?", ["sq-1"],
                   claim_type=ClaimType.OPEN_QUESTION),
        ]
        result = _analyze(claims, plan)
        self.assertEqual(result.findings, [])

    def test_hypotheses_from_entity_cooccurrence(self):
        plan = _plan(subquestions=1)
        claims = [
            _claim("claim-1", "Batteries and inverters work together.", ["sq-1"],
                   sources=2),
        ]
        claims[0].entities = ["Battery", "Inverter"]
        result = _analyze(claims, plan)
        self.assertTrue(result.hypotheses)
        self.assertIn("Battery", result.hypotheses[0].statement)
        self.assertEqual(result.hypotheses[0].claim_ids, ["claim-1"])

    def test_overall_confidence_reflects_coverage(self):
        # Same claims; a plan with an unanswered subquestion scores lower.
        claims1 = [_claim("claim-1", "X.", ["sq-1"], sources=2, agreement=0.5)]
        claims2 = [_claim("claim-1", "X.", ["sq-1"], sources=2, agreement=0.5)]
        full = _analyze(claims1, _plan(subquestions=1))
        partial = _analyze(claims2, _plan(subquestions=2))
        self.assertGreater(full.confidence.score, partial.confidence.score)
        self.assertEqual(full.confidence.coverage, 1.0)
        self.assertEqual(partial.confidence.coverage, 0.5)

    def test_executive_summary_mentions_question(self):
        plan = _plan(subquestions=1)
        claims = [_claim("claim-1", "X works.", ["sq-1"], sources=2)]
        result = _analyze(claims, plan)
        self.assertIn(plan.question, result.executive_summary)


if __name__ == "__main__":
    unittest.main()
