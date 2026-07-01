import os
import tempfile
import unittest

from tests import _path  # noqa: F401

from research_engine.config import EngineConfig
from research_engine.domain.models import RawDocument, ResearchRequest, Source, TaskStatus
from research_engine.orchestrator.orchestrator import ResearchOrchestrator
from research_engine.providers.base import SearchProvider
from research_engine.providers.offline import NullLLMProvider, OfflineSearchProvider
from research_engine.storage.storage import SessionStorage


class _FailingSearchProvider(SearchProvider):
    name = "failing"

    def search(self, query, limit):
        raise RuntimeError("provider down")


def _run(search_provider, tmp, **cfg_overrides):
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
        topic="Renewable Energy",
        max_subtopics=config.max_subtopics,
        documents_per_query=config.documents_per_query,
    )
    return orchestrator.run(request), config


class EndToEndTests(unittest.TestCase):
    def test_full_pipeline_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            session, config = _run(OfflineSearchProvider(), tmp)

            self.assertEqual(session.status, TaskStatus.COMPLETED)
            self.assertTrue(session.evidence)
            self.assertTrue(session.findings)
            self.assertTrue(session.entities)
            self.assertIsNotNone(session.report)

            expected = os.path.join(config.output_dir, "Renewable Energy_report.md")
            self.assertTrue(os.path.exists(expected))
            with open(expected, encoding="utf-8") as handle:
                self.assertIn("# Research Report: Renewable Energy", handle.read())

    def test_deterministic_across_runs(self):
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            s1, _ = _run(OfflineSearchProvider(), tmp1)
            s2, _ = _run(OfflineSearchProvider(), tmp2)
            self.assertEqual(
                [e.claim for e in s1.evidence],
                [e.claim for e in s2.evidence],
            )
            self.assertEqual(
                [f.statement for f in s1.findings],
                [f.statement for f in s2.findings],
            )

    def test_run_survives_failing_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            session, _ = _run(_FailingSearchProvider(), tmp)
            # The run still completes and persists a report, even with no evidence.
            self.assertEqual(session.status, TaskStatus.COMPLETED)
            self.assertEqual(session.evidence, [])
            self.assertTrue(
                any(t.status == TaskStatus.FAILED for t in session.tasks)
            )
            self.assertIsNotNone(session.report)


if __name__ == "__main__":
    unittest.main()
