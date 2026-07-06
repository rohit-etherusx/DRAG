"""Engine service layer.

A single entry point that turns an :class:`EngineConfig` + topic into a completed
:class:`ResearchSession`. Both the CLI and the HTTP API call this, so provider
wiring and the run lifecycle live in exactly one place.
"""
from __future__ import annotations

from research_engine.config import EngineConfig
from research_engine.domain.models import ResearchRequest, ResearchSession
from research_engine.orchestrator.orchestrator import ResearchOrchestrator
from research_engine.progress import ProgressReporter
from research_engine.providers.factory import build_llm_provider, build_search_provider
from research_engine.storage.storage import SessionStorage


def run_research(
    topic: str,
    config: EngineConfig,
    progress: ProgressReporter | None = None,
) -> ResearchSession:
    """Run a full research session for ``topic`` using ``config``.

    Builds the configured search and LLM providers, wires them into an
    orchestrator with storage, and executes the session (which also persists the
    report and snapshot). Returns the completed session.

    ``progress`` is an optional observe-only reporter (see ``progress.py``) used
    by interactive front-ends (the TUI) to watch the run live; omitting it is
    the default, unobserved path.
    """
    request = ResearchRequest(
        topic=topic,
        max_subtopics=config.max_subtopics,
        documents_per_query=config.documents_per_query,
    )
    orchestrator = ResearchOrchestrator(
        config=config,
        search_provider=build_search_provider(config),
        llm_provider=build_llm_provider(config),
        storage=SessionStorage(config.output_dir, config.sessions_dir),
    )
    return orchestrator.run(request, progress=progress)
