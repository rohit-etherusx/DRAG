import unittest

from tests import _path  # noqa: F401  (path setup side effect)

from research_engine.domain.models import Task, TaskKind
from research_engine.taskgraph.graph import TaskGraph, TaskGraphError


def _task(tid, deps=None):
    return Task(id=tid, description=tid, kind=TaskKind.COLLECT, depends_on=deps or [])


class TaskGraphTests(unittest.TestCase):
    def test_topological_order_respects_dependencies(self):
        graph = TaskGraph([
            _task("a"),
            _task("b"),
            _task("c", deps=["a", "b"]),
        ])
        order = [t.id for t in graph.topological_order()]
        self.assertLess(order.index("a"), order.index("c"))
        self.assertLess(order.index("b"), order.index("c"))

    def test_order_is_deterministic(self):
        graph = TaskGraph([_task("a"), _task("b"), _task("c", deps=["a"])])
        first = [t.id for t in graph.topological_order()]
        second = [t.id for t in graph.topological_order()]
        self.assertEqual(first, second)

    def test_duplicate_id_rejected(self):
        graph = TaskGraph([_task("a")])
        with self.assertRaises(TaskGraphError):
            graph.add(_task("a"))

    def test_unknown_dependency_rejected(self):
        graph = TaskGraph([_task("a", deps=["missing"])])
        with self.assertRaises(TaskGraphError):
            graph.topological_order()

    def test_cycle_detected(self):
        graph = TaskGraph([_task("a", deps=["b"]), _task("b", deps=["a"])])
        with self.assertRaises(TaskGraphError):
            graph.topological_order()

    def test_dependents_of(self):
        graph = TaskGraph([_task("a"), _task("b", deps=["a"])])
        self.assertEqual([t.id for t in graph.dependents_of("a")], ["b"])


if __name__ == "__main__":
    unittest.main()
