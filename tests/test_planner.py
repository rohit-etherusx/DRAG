import json
import unittest

from tests import _path  # noqa: F401

from research_engine.domain.models import (
    Claim,
    GapKind,
    KnowledgeGap,
    ResearchRequest,
    TaskKind,
)
from research_engine.planner.planner import ResearchPlanner
from research_engine.providers.base import LLMProvider
from research_engine.state.research_state import ResearchState


class _StubLLM(LLMProvider):
    name = "stub"

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    @property
    def available(self):
        return True

    def generate(self, prompt, system=None, *, json_object=False):
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

class AdaptivePlanningTests(unittest.TestCase):
    def _state(self):
        planner = ResearchPlanner()
        request = ResearchRequest(topic="Solar Power", max_subtopics=2)
        plan = planner.plan(request)
        state = ResearchState(
            session_id="session-test",
            request=request,
            plan=plan,
            tasks=planner.tasks_for(plan).topological_order(),
        )
        return planner, state

    def test_iteration_one_executes_the_initial_plan(self):
        planner, state = self._state()
        tasks = planner.next_search_tasks(state, iteration=1, limit=10)
        self.assertTrue(tasks)
        # Every task carries its objective, reason, and subquestion binding.
        for task in tasks:
            self.assertTrue(task.query)
            self.assertTrue(task.objective)
            self.assertEqual(task.reason, "initial research plan")
            self.assertTrue(task.subquestion_id)
        # Tasks were recorded in the state's search history.
        self.assertTrue(state.was_query_executed(tasks[0].query))

    def test_later_iterations_convert_gaps_into_prioritized_tasks(self):
        planner, state = self._state()
        planner.next_search_tasks(state, iteration=1, limit=10)
        state.add_gaps([
            KnowledgeGap(
                id="", kind=GapKind.MISSING_DEFINITION,
                description="'Inverter' is never defined.",
                suggested_query="what is Inverter",
                subquestion_id=state.plan.subquestions[0].id,
                entity="Inverter", priority=0.7,
            ),
            KnowledgeGap(
                id="", kind=GapKind.MISSING_EVIDENCE,
                description="No evidence for storage.",
                suggested_query="solar storage evidence",
                subquestion_id=state.plan.subquestions[0].id,
                priority=0.9,
            ),
        ])
        # Keep the subquestion active: give it no claims so it isn't satisfied.
        tasks = planner.next_search_tasks(state, iteration=2, limit=10)
        self.assertEqual(len(tasks), 2)
        # Highest-priority gap first; every emitted gap marked investigated.
        self.assertEqual(tasks[0].query, "solar storage evidence")
        self.assertIn("knowledge gap", tasks[0].reason)
        self.assertTrue(all(g.investigated for g in state.gaps))
        # A further pass finds no open gaps -> no tasks.
        self.assertEqual(
            planner.next_search_tasks(state, iteration=3, limit=10), []
        )

    def test_executed_queries_are_reformulated_not_repeated(self):
        planner, state = self._state()
        planner.next_search_tasks(state, iteration=1, limit=10)
        first_query = state.search_tasks[0].query
        state.add_gaps([
            KnowledgeGap(
                id="", kind=GapKind.UNCORROBORATED,
                description="Only one source.",
                suggested_query=first_query,
                subquestion_id=state.plan.subquestions[0].id,
                priority=0.6,
            ),
        ])
        tasks = planner.next_search_tasks(state, iteration=2, limit=10)
        self.assertEqual(len(tasks), 1)
        self.assertNotEqual(tasks[0].query, first_query)
        self.assertIn(first_query, tasks[0].query)  # reformulated, not replaced

    def test_satisfied_branches_are_terminated(self):
        planner, state = self._state()
        planner.next_search_tasks(state, iteration=1, limit=10)
        satisfied = state.plan.subquestions[0].id
        state.claims.append(
            Claim(id="claim-1", text="An answer.", subquestion_ids=[satisfied])
        )
        planner.next_search_tasks(state, iteration=2, limit=10)
        self.assertNotIn(satisfied, state.active_subquestion_ids)
        self.assertIn(satisfied, state.completed_subquestions)


if __name__ == "__main__":
    unittest.main()
