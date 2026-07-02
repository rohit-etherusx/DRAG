import json
import os
import tempfile
import unittest

from tests import _path  # noqa: F401

from research_engine.domain.models import (
    Answer,
    Claim,
    ClaimType,
    ConfidenceReport,
    Contradiction,
    Evidence,
    Finding,
    Hypothesis,
    ResearchPlan,
    ResearchRequest,
    ResearchSession,
    Source,
    SubQuestion,
    Task,
    TaskKind,
    TaskStatus,
    VerificationStatus,
)
from research_engine.report.generator import ReportGenerator
from research_engine.storage.storage import SessionStorage


def _session(is_question=False):
    session = ResearchSession(
        id="session-test",
        request=ResearchRequest("Test Topic"),
        status=TaskStatus.COMPLETED,
        created_at="2020-01-01T00:00:00+00:00",
        completed_at="2020-01-01T00:00:01+00:00",
    )
    session.plan = ResearchPlan(
        objective="Understand Test Topic",
        question="Test Topic",
        is_question=is_question,
        subject="Test Topic",
        subquestions=[SubQuestion(id="sq-1", question="What is Test Topic?")],
        scope="Everything relevant.",
    )
    session.tasks = [
        Task(id="collect-1", description="d", kind=TaskKind.COLLECT,
             query="What is Test Topic?", subquestion_id="sq-1",
             status=TaskStatus.COMPLETED),
    ]
    session.sources = [
        Source(id="src-1", title="Src", provider="test",
               authority=0.65, authority_tier="encyclopedia"),
    ]
    session.evidence = [
        Evidence(id="ev-1", passage="A fact passage.", document_id="doc-1",
                 source_id="src-1", subquestion_id="sq-1"),
    ]
    session.claims = [
        Claim(id="claim-1", text="A verified fact.", claim_type=ClaimType.FACT,
              evidence_ids=["ev-1"], source_ids=["src-1"],
              subquestion_ids=["sq-1"], supporting_sources=2,
              independent_domains=2, agreement=0.5,
              status=VerificationStatus.CORROBORATED, confidence=0.6),
    ]
    session.findings = [
        Finding(id="find-sq-1", statement="A finding.", claim_ids=["claim-1"],
                subquestion_id="sq-1", confidence=0.5,
                confidence_explanation="Confidence 50%: test."),
    ]
    session.confidence = ConfidenceReport(
        score=0.55, independent_sources=2, authority=0.65, agreement=0.5,
        coverage=1.0, contradictions=0, evidence_quality=0.7, specificity=0.4,
        explanation="Confidence 55%: test factors.",
    )
    session.overall_confidence = 0.55
    session.suggestions = ["Do more research."]
    return session


class AdaptiveSectionTests(unittest.TestCase):
    def test_core_sections_render_when_supported(self):
        report = ReportGenerator().generate(_session(), "An executive summary.")
        for section in [
            "## Executive Summary",
            "## Research Plan",
            "## Key Findings",
            "## Verified Claims",
            "## Contradictions",
            "## Uncertainty and Confidence",
            "## Recommendations",
            "## Appendix",
        ]:
            self.assertIn(section, report.markdown, f"missing section: {section}")

    def test_unsupported_sections_are_omitted(self):
        report = ReportGenerator().generate(_session(), "summary")
        # No hypotheses/open questions -> no Future Research section; topic
        # (non-question) input -> no Direct Answer section.
        self.assertNotIn("## Future Research", report.markdown)
        self.assertNotIn("## Direct Answer", report.markdown)

    def test_empty_session_states_missing_evidence_instead_of_padding(self):
        session = _session()
        session.claims = []
        session.findings = []
        session.evidence = []
        session.missing_evidence = ["No verified evidence was collected for: X?"]
        report = ReportGenerator().generate(session, "summary")
        self.assertNotIn("## Key Findings", report.markdown)
        self.assertNotIn("## Verified Claims", report.markdown)
        self.assertIn("## Limitations and Missing Evidence", report.markdown)
        self.assertIn("No verified evidence was collected", report.markdown)

    def test_question_session_renders_direct_answer(self):
        session = _session(is_question=True)
        session.answer = Answer(
            text="The direct answer to the question.",
            reasoning="Synthesized from 1 verified claim.",
            confidence=0.6,
            claim_ids=["claim-1"],
        )
        session.direct_answer = session.answer.text
        report = ReportGenerator().generate(session, "summary")
        self.assertIn("## Direct Answer", report.markdown)
        self.assertIn("The direct answer to the question.", report.markdown)
        self.assertIn("Synthesized from 1 verified claim.", report.markdown)

    def test_unanswerable_question_is_stated_explicitly(self):
        session = _session(is_question=True)
        session.answer = None
        session.direct_answer = ""
        report = ReportGenerator().generate(session, "summary")
        self.assertIn(
            "insufficient to answer the research objective", report.markdown
        )

    def test_future_research_renders_with_hypotheses(self):
        session = _session()
        session.hypotheses = [
            Hypothesis(id="hyp-1", statement="Maybe X causes Y.", confidence=0.4)
        ]
        session.open_questions = ["What about Z?"]
        report = ReportGenerator().generate(session, "summary")
        self.assertIn("## Future Research", report.markdown)
        self.assertIn("Maybe X causes Y.", report.markdown)
        self.assertIn("What about Z?", report.markdown)


class ProvenanceChainTests(unittest.TestCase):
    def test_findings_cite_claims_and_claims_cite_evidence_and_sources(self):
        report = ReportGenerator().generate(_session(), "summary")
        # finding -> claim
        self.assertIn("[`claim-1`]", report.markdown)
        # claim -> evidence -> source label
        self.assertIn("[evidence: ev-1 → S1]", report.markdown)
        # source listed with authority
        self.assertIn("[S1] *Src*", report.markdown)
        self.assertIn("encyclopedia", report.markdown)

    def test_uncertainty_section_shows_factor_breakdown(self):
        report = ReportGenerator().generate(_session(), "summary")
        self.assertIn("| Independent sources | 2 |", report.markdown)
        self.assertIn("| Plan coverage | 100% |", report.markdown)
        self.assertIn("Confidence 55%: test factors.", report.markdown)

    def test_contradictions_reference_claim_ids(self):
        session = _session()
        session.contradictions = [
            Contradiction(id="contra-1", description='"A" vs "B"',
                          claim_ids=["claim-1", "claim-2"]),
        ]
        report = ReportGenerator().generate(session, "summary")
        self.assertIn('"A" vs "B"', report.markdown)
        self.assertIn("claim-1, claim-2", report.markdown)


class StorageTests(unittest.TestCase):
    def test_report_written_with_convention_and_session_roundtrips(self):
        session = _session()
        session.report = ReportGenerator().generate(session, "summary")
        with tempfile.TemporaryDirectory() as tmp:
            storage = SessionStorage(
                output_dir=os.path.join(tmp, "report"),
                sessions_dir=os.path.join(tmp, "sessions"),
            )
            report_path = storage.save_report(session)
            session_path = storage.save_session(session)

            self.assertTrue(report_path.endswith("Test Topic_report.md"))
            self.assertTrue(os.path.exists(report_path))

            with open(session_path, encoding="utf-8") as handle:
                data = json.load(handle)
            self.assertEqual(data["request"]["topic"], "Test Topic")
            self.assertEqual(data["status"], "completed")
            self.assertEqual(data["tasks"][0]["kind"], "collect")
            # Claim-centric fields serialize, enums included.
            self.assertEqual(data["claims"][0]["claim_type"], "fact")
            self.assertEqual(data["claims"][0]["status"], "corroborated")
            self.assertEqual(data["plan"]["subquestions"][0]["id"], "sq-1")
            self.assertEqual(data["confidence"]["score"], 0.55)

    def test_save_report_without_report_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = SessionStorage(output_dir=tmp, sessions_dir=tmp)
            with self.assertRaises(ValueError):
                storage.save_report(_session())


if __name__ == "__main__":
    unittest.main()
