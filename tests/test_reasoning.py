import unittest

from tests import _path  # noqa: F401

from research_engine.domain.models import Evidence, Task, TaskKind
from research_engine.knowledge.graph import KnowledgeGraph
from research_engine.reasoning.analyzer import ReasoningEngine


class ReasoningTests(unittest.TestCase):
    def setUp(self):
        self.tasks = [
            Task(id="collect-1", description="d", kind=TaskKind.COLLECT,
                 query="Overview of X"),
            Task(id="synthesize-1", description="s", kind=TaskKind.SYNTHESIZE,
                 query="X", depends_on=["collect-1"]),
        ]
        self.evidence = [
            Evidence(id="ev-1", claim="X involves Alpha and Beta.",
                     source_id="src-1", task_id="collect-1",
                     entities=["Alpha", "Beta"]),
            Evidence(id="ev-2", claim="Alpha supports Beta.",
                     source_id="src-2", task_id="collect-1",
                     entities=["Alpha", "Beta"]),
        ]
        self.graph = KnowledgeGraph()
        self.graph.build(self.evidence)

    def _analyze(self, docs_per_query=3):
        return ReasoningEngine(llm=None).analyze(
            topic="X",
            tasks=self.tasks,
            evidence=self.evidence,
            knowledge_graph=self.graph,
            contradictions=[],
            documents_per_query=docs_per_query,
        )

    def test_produces_one_finding_per_collect_task(self):
        result = self._analyze()
        self.assertEqual(len(result.findings), 1)
        self.assertTrue(result.findings[0].supporting_evidence_ids)

    def test_confidence_stays_below_certainty(self):
        # 2 distinct sources / (3 + 1) = 0.5
        result = self._analyze(docs_per_query=3)
        self.assertAlmostEqual(result.findings[0].confidence, 0.5)
        self.assertLess(result.overall_confidence, 1.0)

    def test_generates_hypotheses_from_relationships(self):
        result = self._analyze()
        self.assertTrue(result.hypotheses)
        self.assertIn("Alpha", result.hypotheses[0].statement)

    def test_open_questions_and_suggestions_present(self):
        result = self._analyze()
        self.assertTrue(result.open_questions)
        self.assertTrue(result.suggestions)

    def test_deterministic_summary_without_llm(self):
        result = self._analyze()
        self.assertIn("X", result.executive_summary)

    def test_low_source_diversity_flags_open_question(self):
        # Only one source -> distinct_sources < 2 for the collect task.
        self.evidence = [
            Evidence(id="ev-1", claim="X is real.", source_id="src-1",
                     task_id="collect-1", entities=["Alpha"]),
        ]
        self.graph = KnowledgeGraph()
        self.graph.build(self.evidence)
        result = self._analyze()
        self.assertTrue(
            any("corroborate" in q for q in result.open_questions)
        )


if __name__ == "__main__":
    unittest.main()
