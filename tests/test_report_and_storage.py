import json
import os
import tempfile
import unittest

from tests import _path  # noqa: F401

from research_engine.domain.models import (
    Evidence,
    Finding,
    ResearchReport,
    ResearchRequest,
    ResearchSession,
    Source,
    Task,
    TaskKind,
    TaskStatus,
)
from research_engine.report.generator import ReportGenerator
from research_engine.storage.storage import SessionStorage

_REQUIRED_SECTIONS = [
    "## Executive Summary",
    "## Research Objectives",
    "## Key Findings",
    "## Supporting Evidence",
    "## Extracted Entities",
    "## Relationships Between Entities",
    "## Generated Hypotheses",
    "## Confidence Assessment",
    "## Contradictions and Conflicting Evidence",
    "## Open Questions",
    "## Suggestions for Further Investigation",
    "## Citations and References",
]


def _session():
    session = ResearchSession(
        id="session-test",
        request=ResearchRequest("Test Topic"),
        status=TaskStatus.COMPLETED,
        created_at="2020-01-01T00:00:00+00:00",
        completed_at="2020-01-01T00:00:01+00:00",
    )
    session.tasks = [
        Task(id="collect-1", description="d", kind=TaskKind.COLLECT,
             query="Overview of Test Topic", status=TaskStatus.COMPLETED),
    ]
    session.sources = [Source(id="src-1", title="Src", provider="test")]
    session.evidence = [
        Evidence(id="ev-1", claim="A fact.", source_id="src-1", task_id="collect-1"),
    ]
    session.findings = [
        Finding(id="find-1", statement="A finding.",
                supporting_evidence_ids=["ev-1"], confidence=0.5),
    ]
    return session


class ReportTests(unittest.TestCase):
    def test_report_contains_all_required_sections(self):
        report = ReportGenerator().generate(_session(), "An executive summary.")
        for section in _REQUIRED_SECTIONS:
            self.assertIn(section, report.markdown, f"missing section: {section}")

    def test_findings_cite_sources(self):
        report = ReportGenerator().generate(_session(), "summary")
        self.assertIn("[S1]", report.markdown)


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

    def test_save_report_without_report_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = SessionStorage(output_dir=tmp, sessions_dir=tmp)
            with self.assertRaises(ValueError):
                storage.save_report(_session())


if __name__ == "__main__":
    unittest.main()
