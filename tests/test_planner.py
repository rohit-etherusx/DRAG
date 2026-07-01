import unittest

from tests import _path  # noqa: F401

from research_engine.domain.models import ResearchRequest, TaskKind
from research_engine.planner.planner import ResearchPlanner


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.planner = ResearchPlanner()

    def test_plan_produces_collect_and_synthesize_tasks(self):
        graph = self.planner.plan(ResearchRequest("Photosynthesis", max_subtopics=4))
        collect = [t for t in graph.tasks if t.kind is TaskKind.COLLECT]
        synth = [t for t in graph.tasks if t.kind is TaskKind.SYNTHESIZE]
        self.assertEqual(len(collect), 4)
        self.assertEqual(len(synth), 1)

    def test_synthesis_depends_on_all_collection_tasks(self):
        graph = self.planner.plan(ResearchRequest("Photosynthesis", max_subtopics=3))
        synth = next(t for t in graph.tasks if t.kind is TaskKind.SYNTHESIZE)
        collect_ids = {t.id for t in graph.tasks if t.kind is TaskKind.COLLECT}
        self.assertEqual(set(synth.depends_on), collect_ids)

    def test_queries_embed_topic(self):
        graph = self.planner.plan(ResearchRequest("Black Holes", max_subtopics=2))
        for task in graph.tasks:
            if task.kind is TaskKind.COLLECT:
                self.assertIn("Black Holes", task.query)

    def test_max_subtopics_is_bounded(self):
        graph = self.planner.plan(ResearchRequest("X", max_subtopics=100))
        collect = [t for t in graph.tasks if t.kind is TaskKind.COLLECT]
        self.assertLessEqual(len(collect), 7)  # number of defined angles

    def test_empty_topic_rejected(self):
        with self.assertRaises(ValueError):
            self.planner.plan(ResearchRequest("   "))

    def test_graph_is_acyclic(self):
        graph = self.planner.plan(ResearchRequest("Economics"))
        # Should not raise.
        self.assertGreater(len(graph.topological_order()), 0)


if __name__ == "__main__":
    unittest.main()
