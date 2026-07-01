"""Research task graph.

Research is represented as a directed acyclic graph of tasks rather than a linear
sequence, so tasks can branch (independent investigations) and converge (a
synthesis task depending on many collection tasks). The graph provides a
dependency-respecting execution order.
"""
from __future__ import annotations

from research_engine.domain.models import Task


class TaskGraphError(ValueError):
    """Raised when the task graph is malformed (missing dep or cycle)."""


class TaskGraph:
    """A directed acyclic graph of :class:`Task` nodes keyed by id."""

    def __init__(self, tasks: list[Task] | None = None) -> None:
        self._tasks: dict[str, Task] = {}
        for task in tasks or []:
            self.add(task)

    def add(self, task: Task) -> None:
        if task.id in self._tasks:
            raise TaskGraphError(f"duplicate task id: {task.id}")
        self._tasks[task.id] = task

    def __len__(self) -> int:
        return len(self._tasks)

    def __contains__(self, task_id: str) -> bool:
        return task_id in self._tasks

    def get(self, task_id: str) -> Task:
        return self._tasks[task_id]

    @property
    def tasks(self) -> list[Task]:
        return list(self._tasks.values())

    def dependents_of(self, task_id: str) -> list[Task]:
        """Return tasks that depend directly on ``task_id``."""
        return [t for t in self._tasks.values() if task_id in t.depends_on]

    def topological_order(self) -> list[Task]:
        """Return tasks in dependency order (dependencies first).

        Raises :class:`TaskGraphError` on an unknown dependency or a cycle.
        Ties are broken by insertion order for deterministic execution.
        """
        indegree: dict[str, int] = {tid: 0 for tid in self._tasks}
        for task in self._tasks.values():
            for dep in task.depends_on:
                if dep not in self._tasks:
                    raise TaskGraphError(
                        f"task {task.id} depends on unknown task {dep}"
                    )
                indegree[task.id] += 1

        # Ready set kept in insertion order for determinism.
        ready = [tid for tid in self._tasks if indegree[tid] == 0]
        ordered: list[Task] = []
        while ready:
            current = ready.pop(0)
            ordered.append(self._tasks[current])
            for dependent in self.dependents_of(current):
                indegree[dependent.id] -= 1
                if indegree[dependent.id] == 0:
                    ready.append(dependent.id)

        if len(ordered) != len(self._tasks):
            raise TaskGraphError("cycle detected in task graph")
        return ordered
