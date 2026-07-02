import json
import unittest

from tests import _path  # noqa: F401

from research_engine.domain.models import ResearchRequest, TaskKind
from research_engine.planner.planner import ResearchPlanner
from research_engine.providers.base import LLMProvider


class _StubLLM(LLMProvider):
    name = "stub"

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    @property
    def available(self):
        return True

    def generate(self, prompt, system=None):
        self.calls += 1
        if not self._responses:
            return None
        return self._responses.pop(0)


class DeterministicTopicPlanTests(unittest.TestCase):
    def setUp(self):
        self.planner = ResearchPlanner()

    def test_topic_produces_facet_subquestions(self):
        plan = self.planner.plan(ResearchRequest(topic="Quantum Computing"))
        self.assertFalse(plan.is_question)
        self.assertEqual(plan.subject, "Quantum Computing")
        self.assertEqual(len(plan.subquestions), 6)  # default max_subtopics
        self.assertTrue(all(sq.search_queries for sq in plan.subquestions))
        self.assertIn("Quantum Computing", plan.subquestions[0].question)
        self.assertEqual(plan.planner, "deterministic")

    def test_max_subtopics_limits_subquestions(self):
        plan = self.planner.plan(
            ResearchRequest(topic="Quantum Computing", max_subtopics=2)
        )
        self.assertEqual(len(plan.subquestions), 2)

    def test_plan_is_deterministic(self):
        request = ResearchRequest(topic="Quantum Computing")
        p1, p2 = self.planner.plan(request), self.planner.plan(request)
        self.assertEqual(
            [sq.question for sq in p1.subquestions],
            [sq.question for sq in p2.subquestions],
        )
        self.assertEqual(p1.objective, p2.objective)

    def test_empty_topic_raises(self):
        with self.assertRaises(ValueError):
            self.planner.plan(ResearchRequest(topic="   "))


class DeterministicQuestionPlanTests(unittest.TestCase):
    def setUp(self):
        self.planner = ResearchPlanner()

    def test_question_mark_is_detected(self):
        plan = self.planner.plan(
            ResearchRequest(topic="What are the risks of quantum computing?")
        )
        self.assertTrue(plan.is_question)
        self.assertEqual(plan.subject, "risks of quantum computing")

    def test_interrogative_without_question_mark_is_detected(self):
        plan = self.planner.plan(
            ResearchRequest(topic="how does photosynthesis work")
        )
        self.assertTrue(plan.is_question)

    def test_question_subquestions_target_the_answer(self):
        plan = self.planner.plan(
            ResearchRequest(topic="What are the risks of quantum computing?")
        )
        questions = " ".join(sq.question for sq in plan.subquestions)
        # The question itself is investigated directly, not just surveyed.
        self.assertIn("What are the risks of quantum computing?", questions)
        self.assertIn("supports or contradicts", questions)

    def test_topic_is_not_mistaken_for_question(self):
        plan = self.planner.plan(ResearchRequest(topic="Renewable Energy"))
        self.assertFalse(plan.is_question)


class LLMPlanTests(unittest.TestCase):
    def _plan_json(self):
        return json.dumps(
            {
                "objective": "Establish the risks quantum computers pose to RSA.",
                "is_question": True,
                "subject": "quantum risk to RSA",
                "subquestions": [
                    {"question": "How does Shor's algorithm break RSA?",
                     "search_queries": ["shor algorithm rsa"]},
                    {"question": "When will quantum computers threaten RSA?",
                     "search_queries": ["quantum computer rsa timeline"]},
                ],
                "expected_entities": ["RSA", "Shor's algorithm"],
                "expected_evidence_types": ["numerical data"],
                "expected_source_types": ["peer-reviewed"],
                "scope": "Cryptographic risk evidence.",
                "exclusion_criteria": ["stock price"],
            }
        )

    def test_llm_plan_is_parsed(self):
        llm = _StubLLM([self._plan_json()])
        plan = ResearchPlanner(llm).plan(
            ResearchRequest(topic="Is RSA at risk from quantum computing?")
        )
        self.assertEqual(plan.planner, "llm")
        self.assertEqual(len(plan.subquestions), 2)
        self.assertEqual(plan.subquestions[0].id, "sq-1")
        self.assertEqual(plan.exclusion_criteria, ["stock price"])
        self.assertTrue(plan.is_question)

    def test_unusable_llm_output_falls_back_to_deterministic(self):
        llm = _StubLLM(["not json", "still not json"])
        plan = ResearchPlanner(llm).plan(ResearchRequest(topic="Renewable Energy"))
        self.assertEqual(plan.planner, "deterministic")
        self.assertTrue(plan.subquestions)

    def test_plan_without_subquestions_is_rejected(self):
        llm = _StubLLM([json.dumps({"objective": "x", "subquestions": []})] * 2)
        plan = ResearchPlanner(llm).plan(ResearchRequest(topic="Renewable Energy"))
        self.assertEqual(plan.planner, "deterministic")


class TaskGraphDerivationTests(unittest.TestCase):
    def test_plan_produces_collect_and_synthesize_tasks(self):
        planner = ResearchPlanner()
        plan = planner.plan(ResearchRequest(topic="Solar Power", max_subtopics=3))
        tasks = planner.tasks_for(plan).topological_order()
        collect = [t for t in tasks if t.kind is TaskKind.COLLECT]
        synth = [t for t in tasks if t.kind is TaskKind.SYNTHESIZE]
        self.assertEqual(len(collect), 3)
        self.assertEqual(len(synth), 1)
        # Every collect task is bound to its subquestion.
        self.assertEqual(
            [t.subquestion_id for t in collect], ["sq-1", "sq-2", "sq-3"]
        )
        # Synthesis converges on every collection task.
        self.assertEqual(set(synth[0].depends_on), {t.id for t in collect})

    def test_follow_up_queries_differ_from_originals_and_are_deterministic(self):
        planner = ResearchPlanner()
        plan = planner.plan(ResearchRequest(topic="Solar Power", max_subtopics=2))
        subquestion = plan.subquestions[0]
        q1 = planner.follow_up_queries(plan, subquestion, iteration=2)
        q2 = planner.follow_up_queries(plan, subquestion, iteration=2)
        self.assertEqual(q1, q2)
        self.assertTrue(q1)
        for query in q1:
            self.assertNotIn(query, subquestion.search_queries)


if __name__ == "__main__":
    unittest.main()
