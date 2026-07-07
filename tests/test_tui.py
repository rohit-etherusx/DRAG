"""Tests for the TUI track: the observer seam and the Rich dashboard.

The seam tests are rich-free (they only exercise the engine's event emission).
The dashboard tests skip cleanly when the optional ``[tui]`` extra is absent,
and a layering test asserts the engine core never imports a rendering library.
"""
import os
import subprocess
import sys
import tempfile
import unittest

from tests import _path  # noqa: F401

from research_engine import progress as P
from research_engine.config import EngineConfig
from research_engine.orchestrator.orchestrator import ResearchOrchestrator
from research_engine.providers.offline import NullLLMProvider, OfflineSearchProvider
from research_engine.domain.models import ResearchRequest
from research_engine.storage.storage import SessionStorage

try:
    import rich  # noqa: F401

    _HAS_RICH = True
except ImportError:  # pragma: no cover - depends on install extras
    _HAS_RICH = False


def _run_capturing_events(tmp, topic="photosynthesis"):
    config = EngineConfig(
        output_dir=os.path.join(tmp, "report"),
        sessions_dir=os.path.join(tmp, "sessions"),
        search_provider="offline",
        llm_enabled=False,
    )
    orchestrator = ResearchOrchestrator(
        config=config,
        search_provider=OfflineSearchProvider(),
        llm_provider=NullLLMProvider(),
        storage=SessionStorage(config.output_dir, config.sessions_dir),
    )
    events = []
    session = orchestrator.run(
        ResearchRequest(topic=topic, max_subtopics=config.max_subtopics,
                        documents_per_query=config.documents_per_query),
        progress=events.append,
    )
    return session, events


class ObserverSeamTests(unittest.TestCase):
    def test_emits_expected_event_stream(self):
        with tempfile.TemporaryDirectory() as tmp:
            _session, events = _run_capturing_events(tmp)

        self.assertIsInstance(events[0], P.SessionStarted)
        self.assertEqual(events[0].topic, "photosynthesis")
        self.assertIsInstance(events[1], P.PlanReady)
        self.assertIsInstance(events[-1], P.ReportReady)
        self.assertTrue(events[-1].markdown)
        kinds = {type(e) for e in events}
        for required in (
            P.IterationStarted, P.SearchTaskDone, P.ExtractionDone,
            P.VerificationDone, P.IterationDone,
        ):
            self.assertIn(required, kinds)

    def test_reporter_exception_never_aborts_the_run(self):
        def hostile(_event):
            raise RuntimeError("bad observer")

        with tempfile.TemporaryDirectory() as tmp:
            config = EngineConfig(
                output_dir=os.path.join(tmp, "report"),
                sessions_dir=os.path.join(tmp, "sessions"),
                search_provider="offline", llm_enabled=False,
            )
            orchestrator = ResearchOrchestrator(
                config=config,
                search_provider=OfflineSearchProvider(),
                llm_provider=NullLLMProvider(),
                storage=SessionStorage(config.output_dir, config.sessions_dir),
            )
            session = orchestrator.run(
                ResearchRequest(topic="osmosis"), progress=hostile
            )
        # The hostile reporter raised on every event, yet the run completed.
        self.assertTrue(session.claims)
        self.assertIsNotNone(session.report)

    def test_default_run_has_no_observer(self):
        # Omitting progress must behave exactly as before (no error, full run).
        with tempfile.TemporaryDirectory() as tmp:
            config = EngineConfig(
                output_dir=os.path.join(tmp, "report"),
                sessions_dir=os.path.join(tmp, "sessions"),
                search_provider="offline", llm_enabled=False,
            )
            orchestrator = ResearchOrchestrator(
                config=config,
                search_provider=OfflineSearchProvider(),
                llm_provider=NullLLMProvider(),
                storage=SessionStorage(config.output_dir, config.sessions_dir),
            )
            session = orchestrator.run(ResearchRequest(topic="tides"))
        self.assertTrue(session.claims)


@unittest.skipUnless(_HAS_RICH, "requires the [tui] extra (rich)")
class DashboardControllerTests(unittest.TestCase):
    def _controller_after_events(self):
        from research_engine.cli.controller import TuiController

        controller = TuiController("Hollow Knight", max_iterations=3)
        for event in [
            P.SessionStarted("Hollow Knight", "s"),
            P.PlanReady("obj", [("sq-1", "What is gameplay?")], "llm"),
            P.IterationStarted(1, 1, "initial plan"),
            P.SearchTaskDone(1, "st-1-1", "hollow knight", "sq-1", 8, 3, 3, 11),
            P.ExtractionDone(1, 3, 45),
            P.VerificationDone(1, 71, 4, 67),
            P.IterationDone(1, 1.0, 1.0, 0.68, 7, 7),
            P.AnswerReady("A 2017 Metroidvania.", 0.68),
        ]:
            controller(event)
        return controller

    def test_events_update_state(self):
        controller = self._controller_after_events()
        self.assertEqual(controller.counts["documents"], 3)
        self.assertEqual(controller.counts["extracted"], 45)
        self.assertEqual(controller.counts["verified"], 71)
        self.assertEqual(controller.counts["corroborated"], 4)
        self.assertAlmostEqual(controller.confidence, 0.68)
        self.assertTrue(controller.subquestions["sq-1"]["seen"])

    def test_renders_without_error_and_shows_data(self):
        from rich.console import Console

        controller = self._controller_after_events()
        console = Console(force_terminal=True, width=100, height=40)
        with console.capture() as capture:
            console.print(controller)
        out = capture.get()
        for token in ("Hollow Knight", "Knowledge", "corroborated", "68%"):
            self.assertIn(token, out)

    def test_report_markdown_takes_over_report_panel(self):
        from rich.console import Console

        controller = self._controller_after_events()
        controller(P.ReportReady("# Heading\n\nBody text here.", "/tmp/r.md"))
        console = Console(force_terminal=True, width=100, height=40)
        with console.capture() as capture:
            console.print(controller)
        self.assertIn("Heading", capture.get())


class LayeringTests(unittest.TestCase):
    def test_engine_core_does_not_import_rich(self):
        # The engine must run without the [tui] extra; importing the service
        # and orchestrator must not pull in a rendering library.
        code = (
            "import research_engine.service, "
            "research_engine.orchestrator.orchestrator, sys; "
            "print('rich' in sys.modules)"
        )
        src = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "core-engine",
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            env={**os.environ, "PYTHONPATH": src},
            capture_output=True, text=True,
        )
        self.assertEqual(result.stdout.strip(), "False", result.stderr)


if __name__ == "__main__":
    unittest.main()
