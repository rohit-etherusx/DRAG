"""Research planner.

Turns a topic into a set of collection tasks (one per research angle) plus a
final synthesis task that depends on all of them. The angles are domain-agnostic
so the planner works for any subject. Planning is deterministic, which keeps
whole-session runs reproducible.
"""
from __future__ import annotations

from research_engine.domain.models import ResearchRequest, Task, TaskKind
from research_engine.taskgraph.graph import TaskGraph

# Domain-agnostic research angles, phrased as "<angle> of <topic>" queries.
_ANGLES = [
    "Overview and definition of {topic}",
    "History and background of {topic}",
    "Key concepts and components of {topic}",
    "Current state and developments in {topic}",
    "Challenges and open problems in {topic}",
    "Applications and impact of {topic}",
    "Future directions of {topic}",
]


class ResearchPlanner:
    """Builds a :class:`TaskGraph` from a :class:`ResearchRequest`."""

    def plan(self, request: ResearchRequest) -> TaskGraph:
        topic = request.topic.strip()
        if not topic:
            raise ValueError("research topic must not be empty")

        limit = max(1, min(request.max_subtopics, len(_ANGLES)))
        graph = TaskGraph()
        collect_ids: list[str] = []
        for index in range(limit):
            query = _ANGLES[index].format(topic=topic)
            task_id = f"collect-{index + 1}"
            graph.add(
                Task(
                    id=task_id,
                    description=f"Collect information: {query}",
                    kind=TaskKind.COLLECT,
                    query=query,
                )
            )
            collect_ids.append(task_id)

        # Convergence: a synthesis task depends on every collection task.
        graph.add(
            Task(
                id="synthesize-1",
                description=f"Synthesize findings for: {topic}",
                kind=TaskKind.SYNTHESIZE,
                query=topic,
                depends_on=collect_ids,
            )
        )
        return graph
