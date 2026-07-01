"""Command-line interface.

Wires configuration and providers into a :class:`ResearchOrchestrator`, runs a
research session for the supplied topic, and prints a short summary. This is the
single interactive surface for v0.1 (no TUI/API, per the objective's scope).
"""
from __future__ import annotations

import argparse
import sys

from research_engine.config import EngineConfig
from research_engine.domain.models import ResearchRequest, ResearchSession
from research_engine.logging_setup import configure_logging, get_logger
from research_engine.orchestrator.orchestrator import ResearchOrchestrator
from research_engine.providers.factory import build_llm_provider, build_search_provider
from research_engine.storage.storage import SessionStorage

_log = get_logger("cli")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="research-engine",
        description="Autonomous, domain-agnostic research engine (v0.1).",
    )
    parser.add_argument("topic", nargs="+", help="The topic to research.")
    parser.add_argument(
        "--max-subtopics", type=int, default=None,
        help="Maximum number of research angles to investigate.",
    )
    parser.add_argument(
        "--documents-per-query", type=int, default=None,
        help="Number of documents to gather per research angle.",
    )
    parser.add_argument("--output-dir", default=None, help="Directory for reports.")
    parser.add_argument(
        "--sessions-dir", default=None, help="Directory for session snapshots."
    )
    parser.add_argument(
        "--no-llm", action="store_true",
        help="Disable the LLM provider and use deterministic synthesis only.",
    )
    parser.add_argument(
        "--offline", action="store_true",
        help="Use the deterministic offline search provider (no network). "
             "Reproducible, but evidence is synthetic rather than real.",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable debug logging."
    )
    return parser


def run(argv: list[str] | None = None) -> ResearchSession:
    """Parse arguments, execute a research session, and return it."""
    args = build_arg_parser().parse_args(argv)
    topic = " ".join(args.topic).strip()

    config = EngineConfig.from_env(
        output_dir=args.output_dir,
        sessions_dir=args.sessions_dir,
        max_subtopics=args.max_subtopics,
        documents_per_query=args.documents_per_query,
        llm_enabled=(False if args.no_llm else None),
        search_provider=("offline" if args.offline else None),
        log_level=("DEBUG" if args.verbose else None),
    )
    configure_logging(config.log_level)

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
    return orchestrator.run(request)


def main(argv: list[str] | None = None) -> int:
    """Console entry point. Returns a process exit code."""
    try:
        session = run(argv)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover - defensive top-level guard
        print(f"unexpected error: {exc}", file=sys.stderr)
        return 1

    _print_summary(session)
    return 0


def _print_summary(session: ResearchSession) -> None:
    report_path = session.report.file_path if session.report else "(none)"
    print(f"\nResearch complete: {session.request.topic}")
    print(f"  Status:            {session.status.value}")
    print(f"  Findings:          {len(session.findings)}")
    print(f"  Evidence items:    {len(session.evidence)}")
    print(f"  Entities:          {len(session.entities)}")
    print(f"  Hypotheses:        {len(session.hypotheses)}")
    print(f"  Overall confidence: {session.overall_confidence:.0%}")
    print(f"  Report:            {report_path}")
