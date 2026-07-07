"""Tests for the v0.5.1 quality fixes.

Three targeted fixes made after a live grounded run exposed two quality
defects unrelated to the (separate) performance work:

* **Q1 — corroboration stuck at 0%.** Cross-source corroboration depends on the
  LLM equivalence judge, which was returning unusable free-form JSON on the
  configured model, collapsing every claim to single-source. Fix: request the
  provider's structured-output (JSON) mode on every JSON-returning call — claim
  extraction, the equivalence judge, and the LLM planner.
* **Q2 — topic drift.** Gap-driven search queries were built from generic
  subquestion/claim keywords ("critical reception") with no topic anchor, so a
  "Hollow Knight" run retrieved Harry-Potter and impressionism pages, and the
  low relevance gate let them through. Fix: anchor every gap query to the
  research subject, and reject candidates that share no subject term.
"""
import unittest

from tests import _path  # noqa: F401

from research_engine.domain.models import (
    Claim,
    Evidence,
    RawDocument,
    ResearchPlan,
    ResearchRequest,
    SearchCandidate,
    Source,
    SubQuestion,
)
from research_engine.planner.planner import ResearchPlanner
from research_engine.processing.extraction import (
    HeuristicClaimExtractor,
    LLMClaimExtractor,
)
from research_engine.providers.base import LLMProvider
from research_engine.ranking.evaluator import CandidateEvaluator
from research_engine.reasoning.curiosity import CuriosityEngine, _anchor
from research_engine.verification.equivalence import LLMEquivalenceJudge


class _RecordingLLM(LLMProvider):
    """LLM stub that records the ``json_object`` flag of every call."""

    name = "recording"

    def __init__(self, responses):
        self._responses = list(responses)
        self.json_object_flags: list[bool] = []

    @property
    def available(self):
        return True

    def generate(self, prompt, system=None, *, json_object=False):
        self.json_object_flags.append(json_object)
        return self._responses.pop(0) if self._responses else None


# -- Q1: JSON structured-output mode requested on every JSON call -------------


class JsonModePlumbingTests(unittest.TestCase):
    def test_claim_extraction_requests_json_object(self):
        llm = _RecordingLLM(
            ['{"claims": [{"claim": "A fact.", "type": "fact", '
             '"entities": [], "passage": 0}]}']
        )
        extractor = LLMClaimExtractor(
            llm, objective="obj", fallback=HeuristicClaimExtractor()
        )
        document = RawDocument(
            id="d1", query="q", task_id="t", title="T", content="c",
            source=Source(id="s1", title="s", provider="p"),
        )
        evidence = [
            Evidence(id="ev-1", passage="Some passage.", document_id="d1",
                     source_id="s1")
        ]
        extractor.extract(document, evidence)
        self.assertEqual(llm.json_object_flags, [True])

    def test_equivalence_judge_requests_json_object(self):
        llm = _RecordingLLM(['{"equivalent": []}'])
        judge = LLMEquivalenceJudge(llm)
        judge.equivalent([(Claim(id="c1", text="A."), Claim(id="c2", text="B."))])
        self.assertEqual(llm.json_object_flags, [True])

    def test_llm_planner_requests_json_object(self):
        # Unusable responses force every retry; each must still request JSON
        # mode before the deterministic fallback takes over.
        llm = _RecordingLLM(["not json", "not json"])
        ResearchPlanner(llm).plan(ResearchRequest(topic="Solar energy"))
        self.assertTrue(llm.json_object_flags)
        self.assertTrue(all(llm.json_object_flags))


# -- Q2a: gap queries anchored to the research subject ------------------------


class GapQueryAnchoringTests(unittest.TestCase):
    def _plan(self):
        return ResearchPlan(
            objective="Overview of Hollow Knight",
            question="Hollow Knight",
            subject="Hollow Knight",
            subquestions=[
                SubQuestion(id="sq-1", question="What is the critical reception?")
            ],
        )

    def test_gap_query_is_anchored_to_subject(self):
        gaps = CuriosityEngine().discover(
            plan=self._plan(), claims=[], contradictions=[], entities=[],
            sources={}, active_subquestion_ids={"sq-1"},
        )
        self.assertTrue(gaps)
        for gap in gaps:
            self.assertIn("hollow knight", gap.suggested_query.lower())

    def test_anchor_helper_prefixes_and_avoids_double_anchoring(self):
        self.assertEqual(
            _anchor("critical reception", "Hollow Knight"),
            "Hollow Knight critical reception",
        )
        # Already anchored (case-insensitive) — left unchanged.
        self.assertEqual(
            _anchor("Hollow Knight lore", "Hollow Knight"), "Hollow Knight lore"
        )
        # Empty subject leaves the query untouched.
        self.assertEqual(_anchor("something", ""), "something")


# -- Q2b: candidate gate rejects results sharing no subject term --------------


class SubjectAnchorGateTests(unittest.TestCase):
    def _plan(self, **overrides):
        defaults = dict(
            objective="Overview of Hollow Knight",
            question="Hollow Knight video game",
            subject="Hollow Knight",
            expected_entities=[],
            exclusion_criteria=[],
        )
        defaults.update(overrides)
        return ResearchPlan(**defaults)

    def _candidate(self, url, title, snippet):
        return SearchCandidate(
            id=f"cand-{url}", query="q", title=title, snippet=snippet, url=url,
            provider="web",
        )

    def test_offtopic_candidate_sharing_no_subject_term_is_rejected(self):
        evaluator = CandidateEvaluator(self._plan(), max_accepted=3)
        # Clears the relevance bar on the generic subquestion terms
        # ("critical reception") but shares no subject term.
        offtopic = self._candidate(
            "https://hp.example/", "Harry Potter critical reception",
            "The critical reception and legacy of Harry Potter.",
        )
        outcome = evaluator.evaluate([offtopic], "critical reception")
        self.assertEqual(outcome.accepted, [])
        self.assertIn("off-topic", outcome.rejected[0].rejection_reason)

    def test_ontopic_candidate_is_still_accepted(self):
        evaluator = CandidateEvaluator(self._plan(), max_accepted=3)
        ontopic = self._candidate(
            "https://en.wikipedia.org/wiki/Hollow_Knight",
            "Hollow Knight critical reception",
            "Hollow Knight received critical acclaim on release.",
        )
        outcome = evaluator.evaluate([ontopic], "critical reception")
        self.assertEqual(len(outcome.accepted), 1)
        self.assertTrue(outcome.accepted[0].accepted)

    def test_gate_fails_open_when_subject_has_no_usable_terms(self):
        # A subject too short to yield terms disables the anchor gate entirely.
        evaluator = CandidateEvaluator(
            self._plan(subject="AI", question="AI"), max_accepted=3
        )
        candidate = self._candidate(
            "https://ml.example/", "Machine learning overview",
            "An overview of machine learning and neural networks.",
        )
        outcome = evaluator.evaluate([candidate], "machine learning")
        reasons = [c.rejection_reason for c in outcome.rejected]
        self.assertNotIn("off-topic: shares no subject term", reasons)


if __name__ == "__main__":
    unittest.main()
