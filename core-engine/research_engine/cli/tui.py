"""Animated terminal dashboard entry point (Layer 1).

``research-engine-tui`` runs a research session behind a live Rich dashboard:
animated progress bars and spinners, knowledge counts that update in real time,
and — at the end — the full report rendered to the terminal. It shares the plain
CLI's argument parser and config wiring; only the presentation differs.

When stdout is not a TTY (piped, redirected, CI), it degrades to the plain CLI
so output stays clean and scriptable.
"""
from __future__ import annotations

import sys

from research_engine.cli import app
from research_engine.config import EngineConfig
from research_engine.domain.models import ResearchSession
from research_engine.logging_setup import configure_logging
from research_engine.service import run_research


def _render_outcome(console, session: ResearchSession) -> None:
    """Print the final report and a compact summary below the dashboard."""
    from rich.markdown import Markdown
    from rich.rule import Rule

    console.print(Rule(f"Report · {session.request.topic}", style="green"))
    if session.report and session.report.markdown:
        console.print(Markdown(session.report.markdown))
    report_path = session.report.file_path if session.report else "(none)"
    console.print(Rule(style="green"))
    console.print(
        f"[bold green]✓ complete[/] · {session.iterations} iteration(s) · "
        f"{len(session.claims)} verified claim(s) · confidence "
        f"{session.overall_confidence:.0%} · saved to [cyan]{report_path}[/]"
    )


def run(argv: list[str] | None = None) -> int:
    """Parse arguments, run a session behind the live dashboard, return a code."""
    args = app.build_arg_parser(prog="research-engine-tui").parse_args(argv)
    topic = " ".join(args.topic).strip()
    config = EngineConfig.from_env(
        output_dir=args.output_dir,
        sessions_dir=args.sessions_dir,
        max_subtopics=args.max_subtopics,
        documents_per_query=args.documents_per_query,
        max_iterations=args.max_iterations,
        confidence_threshold=args.confidence_threshold,
        llm_enabled=(False if args.no_llm else None),
        search_provider=("offline" if args.offline else None),
    )

    # No interactive terminal → fall back to the plain, scriptable CLI.
    if not sys.stdout.isatty():
        return app.main(argv)

    # Import Rich lazily so a core install without the [tui] extra still runs
    # the plain CLI; only this interactive path needs it.
    try:
        from rich.console import Console
        from rich.live import Live

        from research_engine.cli.controller import TuiController
    except ImportError:
        print(
            "The dashboard needs the 'tui' extra: pip install "
            "\"research-engine[tui]\"  (falling back to plain output)\n",
            file=sys.stderr,
        )
        return app.main(argv)

    # The dashboard replaces log output; keep logging off the display.
    configure_logging("ERROR")
    console = Console()
    controller = TuiController(topic, config.max_iterations)
    session: ResearchSession | None = None
    try:
        # screen=True renders into the terminal's alternate buffer (like vim /
        # less): Rich owns the whole screen and does flicker-free diff updates,
        # instead of repainting a full-height Layout in place on every refresh.
        # vertical_overflow="crop" keeps a tall region (e.g. the report panel)
        # clipped to its box rather than reflowing the frame. On exit the buffer
        # is restored and the full report is printed to the normal screen below.
        with Live(controller, console=console, refresh_per_second=8,
                  screen=True, vertical_overflow="crop"):
            session = run_research(topic, config, progress=controller)
    except KeyboardInterrupt:
        console.print("\n[yellow]interrupted[/] — research stopped early.")
        return 130
    except Exception as exc:  # surface engine failures cleanly, no traceback wall
        console.print(f"\n[bold red]error:[/] {exc}")
        return 1

    _render_outcome(console, session)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Console entry point for ``research-engine-tui``."""
    return run(argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
