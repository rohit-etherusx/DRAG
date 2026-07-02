import os
import tempfile
import unittest

from tests import _path  # noqa: F401

from research_engine.config import EngineConfig
from research_engine.domain.models import ResearchRequest, TaskStatus
from research_engine.orchestrator.orchestrator import ResearchOrchestrator
from research_engine.providers.base import SearchProvider
from research_engine.providers.offline import NullLLMProvider, OfflineSearchProvider
from research_engine.storage.storage import SessionStorage


class _FailingSearchProvider(SearchProvider):
    name = "failing"

    def search_candidates(self, query, limit):
        raise RuntimeError("provider down")

    def fetch(self, candidate):
        raise RuntimeError("provider down")


def _run(search_provider, tmp, topic="Renewable Energy", **cfg_overrides):
    config = EngineConfig(
        output_dir=os.path.join(tmp, "report"),
        sessions_dir=os.path.join(tmp, "sessions"),
        **cfg_overrides,
    )
    orchestrator = ResearchOrchestrator(
        config=config,
        search_provider=search_provider,
        llm_provider=NullLLMProvider(),
        storage=SessionStorage(config.output_dir, config.sessions_dir),
    )
    request = ResearchRequest(
        topic=topic,
        max_subtopics=config.max_subtopics,
        documents_per_query=config.documents_per_query,
    )
    return orchestrator.run(request), config


class EndToEndTests(unittest.TestCase):
    def test_full_pipeline_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            session, config = _run(OfflineSearchProvider(), tmp)

            self.assertEqual(session.status, TaskStatus.COMPLETED)
            self.assertIsNotNone(session.plan)
            self.assertTrue(session.candidates)
            self.assertTrue(session.documents)
            self.assertTrue(session.evidence)
            self.assertTrue(session.claims)
            self.assertTrue(session.findings)
            self.assertTrue(session.graph_nodes)
            self.assertIsNotNone(session.confidence)
            self.assertIsNotNone(session.report)
            # Candidate evaluation rejected something before download.
            self.assertGreater(session.candidates_rejected, 0)
            self.assertLess(
                session.documents_downloaded, session.candidates_evaluated
            )
            # Provenance chain: every claim references evidence and a source.
            evidence_ids = {e.id for e in session.evidence}
            source_ids = {s.id for s in session.sources}
            for claim in session.claims:
                self.assertTrue(set(claim.evidence_ids) <= evidence_ids)
                self.assertTrue(set(claim.source_ids) <= source_ids)
            # Every finding references verified claims.
            claim_ids = {c.id for c in session.claims}
            for finding in session.findings:
                self.assertTrue(finding.claim_ids)
                self.assertTrue(set(finding.claim_ids) <= claim_ids)

            expected = os.path.join(config.output_dir, "Renewable Energy_report.md")
            self.assertTrue(os.path.exists(expected))
            with open(expected, encoding="utf-8") as handle:
                self.assertIn("# Research Report: Renewable Energy", handle.read())

    def test_question_input_yields_direct_answer_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            session, _ = _run(
                OfflineSearchProvider(), tmp,
                topic="What are the benefits of renewable energy?",
            )
            self.assertTrue(session.plan.is_question)
            self.assertIn("## Direct Answer", session.report.markdown)

    def test_deterministic_across_runs(self):
        with tempfile.TemporaryDirectory() as tmp1, \
                tempfile.TemporaryDirectory() as tmp2:
            s1, _ = _run(OfflineSearchProvider(), tmp1)
            s2, _ = _run(OfflineSearchProvider(), tmp2)
            self.assertEqual(
                [c.text for c in s1.claims], [c.text for c in s2.claims]
            )
            self.assertEqual(
                [f.statement for f in s1.findings],
                [f.statement for f in s2.findings],
            )
            self.assertEqual(s1.overall_confidence, s2.overall_confidence)

    def test_research_loop_respects_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            # An unreachable threshold forces iteration until the budget is hit
            # (or no actionable gaps remain).
            session, config = _run(
                OfflineSearchProvider(), tmp,
                confidence_threshold=0.99, max_iterations=2,
            )
            self.assertEqual(session.status, TaskStatus.COMPLETED)
            self.assertLessEqual(session.iterations, 2)
            self.assertGreaterEqual(session.iterations, 1)

    def test_run_survives_failing_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            session, _ = _run(_FailingSearchProvider(), tmp)
            # The run still completes and persists a report, even with no
            # evidence — and the report states the gaps explicitly.
            self.assertEqual(session.status, TaskStatus.COMPLETED)
            self.assertEqual(session.claims, [])
            self.assertTrue(session.missing_evidence)
            self.assertIsNotNone(session.report)
            self.assertIn(
                "## Limitations and Missing Evidence", session.report.markdown
            )


if __name__ == "__main__":
    unittest.main()
