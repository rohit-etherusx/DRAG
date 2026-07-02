"""Stopping engine.

Decides when research is complete (``ARCHITECTURE.md`` v0.5). An experienced
researcher stops when enough evidence exists, when further searching has
stopped teaching anything, or when the budget runs out — not after a fixed
number of passes. The decision is deterministic, made from the research state
alone, and always carries an explicit human-readable reason that is persisted
in the session (``stop_reason``) so every run can explain why it ended.

Checked in order (first match wins):

1. **confidence target reached** — the objective is answered well enough;
2. **no actionable gaps** — curiosity found nothing left worth investigating;
3. **budget exhausted** — the iteration budget was spent;
4. **negligible knowledge gain** — the last iteration barely grew the
   knowledge model: more searching is repeating, not learning;
5. **confidence stabilized** — confidence has stopped moving short of the
   threshold: the available sources cannot raise it further.

The engine never performs searches and never mutates state.
"""
from __future__ import annotations

from dataclasses import dataclass

from research_engine.state.research_state import ResearchState


@dataclass(frozen=True)
class StoppingDecision:
    """Whether to stop researching, and why (always explainable)."""

    stop: bool
    reason: str


class StoppingEngine:
    """Deterministic stop/continue decisions for the research loop."""

    def __init__(
        self,
        confidence_threshold: float,
        min_iteration_gain: float,
        min_confidence_delta: float,
        max_iterations: int,
    ) -> None:
        self._confidence_threshold = confidence_threshold
        self._min_gain = min_iteration_gain
        self._min_delta = min_confidence_delta
        self._max_iterations = max(1, max_iterations)

    def decide(self, state: ResearchState) -> StoppingDecision:
        """Decide whether research should stop after the latest iteration."""
        record = state.iteration_records[-1] if state.iteration_records else None
        confidence = record.confidence if record else 0.0

        if confidence >= self._confidence_threshold:
            return StoppingDecision(
                True,
                f"confidence {confidence:.0%} reached the "
                f"{self._confidence_threshold:.0%} target",
            )
        if not state.open_gaps():
            return StoppingDecision(
                True, "no actionable knowledge gaps remain"
            )
        if state.iteration >= self._max_iterations:
            return StoppingDecision(
                True,
                f"search budget exhausted ({self._max_iterations} iterations) "
                f"at confidence {confidence:.0%}",
            )
        if record is not None and state.iteration >= 2:
            if record.knowledge_gain < self._min_gain:
                return StoppingDecision(
                    True,
                    f"knowledge gain {record.knowledge_gain:.0%} fell below "
                    f"{self._min_gain:.0%} — searching has stopped producing "
                    "new knowledge",
                )
            delta = abs(
                state.confidence_history[-1] - state.confidence_history[-2]
            )
            if delta < self._min_delta:
                return StoppingDecision(
                    True,
                    f"confidence stabilized at {confidence:.0%} "
                    f"(changed {delta:.1%} in the last iteration) below the "
                    "target — available sources cannot raise it further",
                )
        return StoppingDecision(
            False,
            f"confidence {confidence:.0%} below target with "
            f"{len(state.open_gaps())} open knowledge gap(s)",
        )
