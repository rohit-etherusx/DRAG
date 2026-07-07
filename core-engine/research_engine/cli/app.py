"""Plain command-line interface.

Wires configuration and providers into a :class:`ResearchOrchestrator`, runs a
research session for the supplied topic, and prints a short summary. This is the
non-interactive surface; the animated dashboard lives in ``cli.tui`` and shares
this module's argument parser and config wiring.
"""
from __future__ import annotations

import argparse
import sys

from research_engine.config import EngineConfig
from research_engine.domain.models import ResearchSession
from research_engine.logging_setup import configure_logging, get_logger
from research_engine.service import run_research

_log = get_logger("cli")


def build_arg_parser(prog: str = "research-engine") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Autonomous, domain-agnostic, claim-centric research engine.",
    )
    parser.add_argument(
        "topic", nargs="+", help="The topic or question to research."
    )
    parser.add_argument(
        "--max-subtopics", type=int, default=None,
        help="Maximum number of subquestions to investigate.",
    )
    parser.add_argument(
        "--documents-per-query", type=int, default=None,
        help="Documents downloaded per subquestion (accepted candidates).",
    )
    parser.add_argument(
        "--max-iterations", type=int, default=None,
        help="Research-loop search budget (retrieval+verification passes).",
    )
    parser.add_argument(
        "--confidence-threshold", type=float, default=None,
        help="Stop iterating once overall confidence reaches this value (0-1).",
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


def config_from_args(args: argparse.Namespace) -> EngineConfig:
    """Build an :class:`EngineConfig` from parsed CLI arguments."""
    return EngineConfig.from_env(
        output_dir=args.output_dir,
        sessions_dir=args.sessions_dir,
        max_subtopics=args.max_subtopics,
        documents_per_query=args.documents_per_query,
        max_iterations=args.max_iterations,
        confidence_threshold=args.confidence_threshold,
        llm_enabled=(False if args.no_llm else None),
        search_provider=("offline" if args.offline else None),
        log_level=("DEBUG" if args.verbose else None),
    )


def run(argv: list[str] | None = None) -> ResearchSession:
    """Parse arguments, execute a research session, and return it."""
    args = build_arg_parser().parse_args(argv)
    topic = " ".join(args.topic).strip()
    config = config_from_args(args)
    configure_logging(config.log_level)
    return run_research(topic, config)


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
    print(f"  Status:             {session.status.value}")
    print(f"  Iterations:         {session.iterations}")
    print(f"  Candidates:         {session.candidates_evaluated} evaluated, "
          f"{session.candidates_rejected} rejected before download")
    print(f"  Documents:          {session.documents_downloaded} downloaded")
    print(f"  Evidence passages:  {len(session.evidence)}")
    print(f"  Verified claims:    {len(session.claims)}")
    print(f"  Findings:           {len(session.findings)}")
    print(f"  Hypotheses:         {len(session.hypotheses)}")
    print(f"  Overall confidence: {session.overall_confidence:.0%}")
    print(f"  Report:             {report_path}")
