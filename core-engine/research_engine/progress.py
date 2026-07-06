"""Progress events — the observer seam (Layer 7 infrastructure).

A running research session is otherwise opaue until it returns: ``run()`` is
synchronous and hands back a completed session only at the end. This module is
the seam that lets an interface (the TUI, and later a streaming HTTP API) watch a
run unfold in real time *without* coupling the engine to any UI.

The engine **emits** typed :class:`ProgressEvent`s at natural checkpoints; a
caller passes an optional ``progress`` reporter to observe them. The contract:

* **Observe-only.** Events carry copies of already-computed values; a reporter
  never feeds anything back, so it cannot change what the engine does or the
  results it produces. Determinism is unaffected.
* **Main-thread only.** The orchestrator emits from its own thread, at the
  sequential loop/merge points — never from the concurrent acquisition workers —
  so a reporter never observes a cross-thread race.
* **Failure-isolated.** :func:`emit` swallows a reporter's exceptions (logged):
  a broken UI must never corrupt a research run.
* **No UI dependencies.** Plain dataclasses and a ``Callable`` — the engine core
  never imports a rendering library; that lives entirely in the ``cli`` package.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from research_engine.logging_setup import get_logger

_log = get_logger("progress")


@dataclass
class ProgressEvent:
    """Base class for every research-progress event."""


@dataclass
class SessionStarted(ProgressEvent):
    topic: str
    session_id: str = ""


@dataclass
class PlanReady(ProgressEvent):
    objective: str
    #: (subquestion id, question) pairs, in plan order.
    subquestions: list[tuple[str, str]] = field(default_factory=list)
    planner: str = ""


@dataclass
class IterationStarted(ProgressEvent):
    iteration: int
    task_count: int
    #: Human label for where the iteration's tasks came from.
    source: str = ""


@dataclass
class SearchTaskDone(ProgressEvent):
    iteration: int
    task_id: str
    query: str
    subquestion_id: str = ""
    candidates: int = 0
    accepted: int = 0
    documents: int = 0
    passages: int = 0
    failed: bool = False


@dataclass
class ExtractionDone(ProgressEvent):
    iteration: int
    documents: int
    claims: int


@dataclass
class VerificationDone(ProgressEvent):
    iteration: int
    claims: int
    corroborated: int
    unsupported: int


@dataclass
class IterationDone(ProgressEvent):
    iteration: int
    novelty: float
    knowledge_gain: float
    confidence: float
    new_gaps: int
    open_gaps: int


@dataclass
class Stopping(ProgressEvent):
    iteration: int
    reason: str


@dataclass
class AnswerReady(ProgressEvent):
    text: str
    confidence: float


@dataclass
class ReportReady(ProgressEvent):
    markdown: str
    path: str


#: A progress reporter observes events. ``None`` means "no observer".
ProgressReporter = Callable[[ProgressEvent], None]


def emit(reporter: ProgressReporter | None, event: ProgressEvent) -> None:
    """Deliver ``event`` to ``reporter`` if present, isolating its failures.

    A ``None`` reporter is a no-op (the default, zero-overhead path). Any
    exception the reporter raises is logged and swallowed so a faulty observer
    can never abort or alter a research run.
    """
    if reporter is None:
        return
    try:
        reporter(event)
    except Exception:  # a broken observer must never corrupt a run
        _log.warning(
            "progress reporter failed on %s", type(event).__name__, exc_info=True
        )


__all__ = [
    "ProgressEvent",
    "SessionStarted",
    "PlanReady",
    "IterationStarted",
    "SearchTaskDone",
    "ExtractionDone",
    "VerificationDone",
    "IterationDone",
    "Stopping",
    "AnswerReady",
    "ReportReady",
    "ProgressReporter",
    "emit",
]
