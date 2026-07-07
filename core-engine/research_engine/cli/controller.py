"""Live dashboard controller (Layer 1).

A :class:`TuiController` is the bridge between the engine's observer seam and a
Rich live display. It is *itself* the progress reporter passed into
``run_research``: each :class:`ProgressEvent` mutates a small block of view
state, and Rich's :class:`~rich.live.Live` re-renders the controller several
times a second on its own thread — so spinners, the elapsed clock, and the
progress bars keep animating even while the engine is blocked on a network call,
and every count updates the instant its event arrives.

Only this package imports Rich; the engine never does. State is guarded by a
lock because the engine mutates it (main thread) while Live reads it (refresh
thread).
"""
from __future__ import annotations

import threading
import time
from collections import deque

from rich.console import Group
from rich.layout import Layout
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.text import Text

from research_engine.progress import (
    AnswerReady,
    ExtractionDone,
    IterationDone,
    IterationStarted,
    PlanReady,
    ProgressEvent,
    ReportReady,
    SearchTaskDone,
    SessionStarted,
    Stopping,
    VerificationDone,
)


def _bar(fraction: float, width: int = 24) -> Text:
    """A coloured proportion bar, e.g. confidence ``▓▓▓▓░░ 68%``."""
    fraction = max(0.0, min(1.0, fraction))
    filled = round(fraction * width)
    colour = "red" if fraction < 0.4 else "yellow" if fraction < 0.7 else "green"
    bar = Text()
    bar.append("█" * filled, style=colour)
    bar.append("░" * (width - filled), style="grey37")
    bar.append(f" {fraction:.0%}", style="bold " + colour)
    return bar


class TuiController:
    """Renders live research progress; usable as a ``progress`` reporter."""

    def __init__(self, topic: str, max_iterations: int) -> None:
        self._lock = threading.RLock()
        self._start = time.monotonic()
        self.topic = topic
        self.max_iterations = max(1, max_iterations)

        self.objective = ""
        self.subquestions: dict[str, dict] = {}  # id -> {question, docs, seen}
        self.iteration = 0
        self.iteration_source = ""
        self.confidence = 0.0
        self.stop_reason = ""
        self.answer = ""
        self.report_markdown = ""

        # Running knowledge counts (real-time).
        self.counts = {
            "candidates": 0, "accepted": 0, "documents": 0, "passages": 0,
            "extracted": 0, "verified": 0, "corroborated": 0, "gaps": 0,
        }
        self.activity: deque[str] = deque(maxlen=9)

        # Animated progress: overall iterations + current iteration's tasks.
        # auto_refresh is off — the outer Live owns the refresh cadence.
        self._overall = Progress(
            TextColumn("[bold]iterations[/]"),
            BarColumn(bar_width=None),
            TaskProgressColumn(),
            auto_refresh=False,
        )
        self._overall_task = self._overall.add_task("", total=self.max_iterations)
        self._tasks = Progress(
            SpinnerColumn(),
            TextColumn("{task.description}"),
            BarColumn(bar_width=None),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            auto_refresh=False,
        )
        self._tasks_task = self._tasks.add_task("waiting…", total=None)

    # -- progress reporter ---------------------------------------------------

    def __call__(self, event: ProgressEvent) -> None:
        """Observer callback: update view state from one progress event."""
        with self._lock:
            self._handle(event)

    def _handle(self, event: ProgressEvent) -> None:
        if isinstance(event, SessionStarted):
            self._log(f"session started · {event.topic}")
        elif isinstance(event, PlanReady):
            self.objective = event.objective
            for sid, question in event.subquestions:
                self.subquestions[sid] = {
                    "question": question, "docs": 0, "seen": False
                }
            self._log(f"plan ready · {len(event.subquestions)} subquestions "
                      f"({event.planner})")
        elif isinstance(event, IterationStarted):
            self.iteration = event.iteration
            self.iteration_source = event.source
            self._tasks.reset(
                self._tasks_task, total=event.task_count,
                description=f"iteration {event.iteration} · {event.source}",
            )
            self._log(f"iteration {event.iteration} · {event.task_count} "
                      f"search task(s) · {event.source}")
        elif isinstance(event, SearchTaskDone):
            self._tasks.advance(self._tasks_task, 1)
            sq = self.subquestions.get(event.subquestion_id)
            if sq is not None:
                sq["docs"] += event.documents
                sq["seen"] = True
            if event.failed:
                self._log(f"[red]✗[/] {event.task_id} · {event.query[:38]}")
            else:
                self.counts["candidates"] += event.candidates
                self.counts["accepted"] += event.accepted
                self.counts["documents"] += event.documents
                self.counts["passages"] += event.passages
                self._log(f"[green]✓[/] {event.task_id} · {event.documents} doc(s)"
                          f" · {event.query[:34]}")
        elif isinstance(event, ExtractionDone):
            self.counts["extracted"] += event.claims
            self._log(f"extracted {event.claims} claim(s) from "
                      f"{event.documents} document(s)")
        elif isinstance(event, VerificationDone):
            self.counts["verified"] = event.claims
            self.counts["corroborated"] = event.corroborated
            self._log(f"verified {event.claims} claim(s) · "
                      f"[green]{event.corroborated} corroborated[/]")
        elif isinstance(event, IterationDone):
            self.confidence = event.confidence
            self.counts["gaps"] = event.open_gaps
            self._overall.update(self._overall_task, completed=event.iteration)
            self._log(f"iteration {event.iteration} · gain "
                      f"{event.knowledge_gain:.0%} · confidence "
                      f"{event.confidence:.0%} · {event.open_gaps} open gap(s)")
        elif isinstance(event, Stopping):
            self.stop_reason = event.reason
            self._log(f"[bold]stopping[/] · {event.reason}")
        elif isinstance(event, AnswerReady):
            self.answer = event.text
            self.confidence = event.confidence
            self._log("answer synthesized")
        elif isinstance(event, ReportReady):
            self.report_markdown = event.markdown
            self._log(f"report written · {event.path}")

    def _log(self, line: str) -> None:
        self.activity.append(line)

    # -- rendering -----------------------------------------------------------

    def __rich__(self) -> Layout:
        with self._lock:
            return self._render()

    def _render(self) -> Layout:
        root = Layout()
        root.split_column(
            Layout(self._header(), name="header", size=3),
            Layout(name="body", ratio=3),
            Layout(self._report_panel(), name="report", ratio=2),
        )
        root["body"].split_row(
            Layout(self._progress_panel(), name="progress", ratio=3),
            Layout(self._knowledge_panel(), name="knowledge", ratio=2),
        )
        return root

    def _header(self) -> Panel:
        elapsed = int(time.monotonic() - self._start)
        clock = f"{elapsed // 60:02d}:{elapsed % 60:02d}"
        line = Text.assemble(
            ("⚗ ", "bold cyan"),
            (self.topic, "bold white"),
            ("   ⏱ ", "cyan"), (clock, "white"),
            (f"   iter {self.iteration}/{self.max_iterations}   ", "cyan"),
        )
        line.append_text(_bar(self.confidence, 16))
        return Panel(line, border_style="cyan", title="Research Engine")

    def _progress_panel(self) -> Panel:
        table = Table.grid(expand=True)
        for sid, sq in self.subquestions.items():
            glyph = "[green]✓[/]" if sq["seen"] else "[grey50]•[/]"
            question = sq["question"]
            question = question[:46] + "…" if len(question) > 47 else question
            table.add_row(f"{glyph} [dim]{sid}[/] {question}  "
                          f"[cyan]{sq['docs']}d[/]")
        body = Group(self._overall, Text(""), self._tasks, Text(""), table)
        return Panel(body, title="Progress", border_style="blue")

    def _knowledge_panel(self) -> Panel:
        table = Table.grid(padding=(0, 1))
        table.add_column(justify="right", style="bold")
        table.add_column()
        rows = [
            ("candidates", self.counts["candidates"]),
            ("accepted", self.counts["accepted"]),
            ("documents", self.counts["documents"]),
            ("passages", self.counts["passages"]),
            ("claims", self.counts["extracted"]),
            ("verified", self.counts["verified"]),
            ("corroborated", self.counts["corroborated"]),
            ("open gaps", self.counts["gaps"]),
        ]
        for label, value in rows:
            table.add_row(str(value), label)
        conf = Text.assemble(("confidence\n", "bold"))
        conf.append_text(_bar(self.confidence, 18))
        return Panel(Group(table, Text(""), conf), title="Knowledge",
                     border_style="magenta")

    def _report_panel(self) -> Panel:
        if self.report_markdown:
            return Panel(Markdown(self.report_markdown), title="Report",
                         border_style="green")
        content: list = []
        if self.answer:
            content.append(Text("Answer", style="bold green"))
            content.append(Text(self.answer))
            content.append(Text(""))
        content.append(Text("Activity", style="bold"))
        for line in self.activity:
            content.append(Text.from_markup(f"[dim]›[/] {line}"))
        return Panel(Group(*content), title="Live",
                     border_style="grey50")
