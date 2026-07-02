import unittest

from tests import _path  # noqa: F401

from research_engine.domain.models import (
    GapKind,
    IterationRecord,
    KnowledgeGap,
    RawDocument,
    ResearchPlan,
    ResearchRequest,
    SearchCandidate,
    SearchTask,
    Source,
    SubQuestion,
)
from research_engine.state.research_state import ResearchState


def _state(subquestions=2):
    request = ResearchRequest(topic="Test")
    plan = ResearchPlan(
        objective="Understand Test",
        question="Test",
        subject="Test",
        subquestions=[
            SubQuestion(id=f"sq-{i}", question=f"Q{i}?")
            for i in range(1, subquestions + 1)
        ],
    )
    return ResearchState(
        session_id="session-test", request=request, plan=plan, tasks=[]
    )


def _gap(kind=GapKind.MISSING_EVIDENCE, subquestion_id="sq-1", entity="",
         priority=0.5):
    return KnowledgeGap(
        id="", kind=kind, description="d", suggested_query="q",
        subquestion_id=subquestion_id, entity=entity, priority=priority,
    )


class SearchHistoryTests(unittest.TestCase):
    def test_queries_are_remembered_case_and_space_insensitively(self):
        state = _state()
        state.record_search_task(SearchTask(id="st-1", query="Solar  Power",
                                            objective="o", reason="r"))
        self.assertTrue(state.was_query_executed("solar power"))
        self.assertFalse(state.was_query_executed("wind power"))

    def test_candidates_mark_urls_visited_and_count_rejections(self):
        state = _state()
        accepted = SearchCandidate(id="c1", query="q", title="t", snippet="s",
                                   url="http://a", provider="p", accepted=True)
        rejected = SearchCandidate(id="c2", query="q", title="t", snippet="s",
                                   url="http://b", provider="p", accepted=False)
        state.add_candidates([accepted, rejected])
        self.assertTrue(state.is_visited("http://a"))
        self.assertTrue(state.is_visited("http://b"))
        self.assertEqual(state.candidates_evaluated, 2)
        self.assertEqual(state.candidates_rejected, 1)


class GapTests(unittest.TestCase):
    def test_gaps_deduplicate_by_identity_and_keep_investigated_flag(self):
        state = _state()
        first = state.add_gaps([_gap()])
        self.assertEqual(len(first), 1)
        state.mark_gap_investigated(first[0].id)
        # Re-discovering the same gap neither duplicates nor reopens it.
        second = state.add_gaps([_gap()])
        self.assertEqual(second, [])
        self.assertEqual(len(state.gaps), 1)
        self.assertTrue(state.gaps[0].investigated)

    def test_open_gaps_sorted_by_priority(self):
        state = _state()
        state.add_gaps([
            _gap(kind=GapKind.MISSING_RELATIONSHIP, entity="a", priority=0.4),
            _gap(kind=GapKind.MISSING_EVIDENCE, priority=0.9),
        ])
        open_gaps = state.open_gaps()
        self.assertEqual([g.priority for g in open_gaps], [0.9, 0.4])


class LifecycleTests(unittest.TestCase):
    def test_subquestion_completion_records_reason(self):
        state = _state()
        state.complete_subquestion("sq-1", "answered")
        self.assertNotIn("sq-1", state.active_subquestion_ids)
        self.assertEqual(state.completed_subquestions["sq-1"], "answered")

    def test_iteration_records_build_confidence_history(self):
        state = _state()
        state.record_iteration(IterationRecord(iteration=1, confidence=0.4))
        state.record_iteration(IterationRecord(iteration=2, confidence=0.6))
        self.assertEqual(state.iteration, 2)
        self.assertEqual(state.confidence_history, [0.4, 0.6])


class SessionRenderingTests(unittest.TestCase):
    def test_to_session_renders_the_state(self):
        state = _state()
        source = Source(id="src-1", title="t", provider="p")
        document = RawDocument(id="doc-1", query="q", task_id="t1",
                               title="d", content="c", source=source)
        state.add_documents([document])
        state.record_search_task(SearchTask(id="st-1", query="q",
                                            objective="o", reason="r"))
        state.add_gaps([_gap()])
        state.record_iteration(IterationRecord(iteration=1, confidence=0.5))
        state.stop_reason = "budget exhausted"

        session = state.to_session()
        self.assertEqual(session.id, "session-test")
        self.assertEqual(session.documents_downloaded, 1)
        self.assertEqual([s.id for s in session.sources], ["src-1"])
        self.assertEqual(len(session.search_tasks), 1)
        self.assertEqual(len(session.knowledge_gaps), 1)
        self.assertEqual(len(session.iteration_records), 1)
        self.assertEqual(session.stop_reason, "budget exhausted")
        self.assertEqual(session.iterations, 1)


if __name__ == "__main__":
    unittest.main()
