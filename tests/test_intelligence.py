"""Tests for the research-intelligence modules: importance, information gain,
curiosity, and stopping."""
import unittest

from tests import _path  # noqa: F401

from research_engine.domain.models import (
    Claim,
    ClaimType,
    Contradiction,
    Entity,
    Evidence,
    GapKind,
    IterationRecord,
    RawDocument,
    ResearchPlan,
    ResearchRequest,
    Source,
    SubQuestion,
)
from research_engine.processing.extraction import ExtractedClaim
from research_engine.reasoning.curiosity import CuriosityEngine
from research_engine.reasoning.gain import InformationGainAnalyzer
from research_engine.reasoning.importance import ImportanceModel
from research_engine.reasoning.stopping import StoppingEngine
from research_engine.state.research_state import ResearchState


def _plan(subquestions=1):
    return ResearchPlan(
        objective="Understand solar energy storage",
        question="Solar energy storage",
        subject="solar energy storage",
        subquestions=[
            SubQuestion(id=f"sq-{i}", question=f"How does solar storage work {i}?")
            for i in range(1, subquestions + 1)
        ],
    )


def _claim(cid, text, claim_type=ClaimType.FACT, entities=None, agreement=0.0,
           sources=1, subquestion_ids=None, importance=0.0):
    return Claim(
        id=cid, text=text, claim_type=claim_type,
        entities=entities or [], agreement=agreement,
        supporting_sources=sources,
        evidence_ids=[f"ev-{cid}"],
        source_ids=[f"src-{i}" for i in range(1, sources + 1)],
        subquestion_ids=subquestion_ids or ["sq-1"],
        importance=importance,
    )


class ImportanceTests(unittest.TestCase):
    def test_relevant_definition_outranks_stray_date(self):
        plan = _plan()
        claims = [
            _claim("c1", "Solar energy storage is defined as storing energy.",
                   claim_type=ClaimType.DEFINITION, entities=["Solar Storage"]),
            _claim("c2", "The office opened in 1987.", claim_type=ClaimType.DATE),
        ]
        entities = [Entity(id="e1", name="Solar Storage", claim_ids=["c1"])]
        ImportanceModel().stamp(claims, plan, entities)
        self.assertGreater(claims[0].importance, claims[1].importance)

    def test_corroboration_raises_importance(self):
        plan = _plan()
        base = "Batteries store solar energy for later use."
        claims = [
            _claim("c1", base, agreement=0.8),
            _claim("c2", base, agreement=0.0),
        ]
        ImportanceModel().stamp(claims, plan, [])
        self.assertGreater(claims[0].importance, claims[1].importance)

    def test_scores_are_bounded_and_deterministic(self):
        plan = _plan()
        claims = [_claim("c1", "Solar energy storage matters.")]
        model = ImportanceModel()
        model.stamp(claims, plan, [])
        first = claims[0].importance
        model.stamp(claims, plan, [])
        self.assertEqual(claims[0].importance, first)
        self.assertGreaterEqual(first, 0.0)
        self.assertLessEqual(first, 1.0)


class InformationGainTests(unittest.TestCase):
    def _document(self, doc_id="doc-1"):
        return RawDocument(
            id=doc_id, query="q", task_id="t", title="T", content="c",
            source=Source(id="src-1", title="s", provider="p"),
        )

    def _evidence(self, eid, doc_id="doc-1", subquestion_id="sq-1"):
        return Evidence(id=eid, passage="p", document_id=doc_id,
                        source_id="src-1", subquestion_id=subquestion_id)

    def test_novel_and_redundant_claims_are_separated(self):
        document = self._document()
        evidence = {e.id: e for e in [self._evidence("ev-1")]}
        prior = [ExtractedClaim(text="Known fact about storage.",
                                evidence_id="ev-0")]
        new = [
            ExtractedClaim(text="Known fact about storage.", evidence_id="ev-1"),
            ExtractedClaim(text="A brand new insight.", evidence_id="ev-1"),
        ]
        record = InformationGainAnalyzer().analyze(
            iteration=2, search_tasks=1,
            new_documents=[document], new_extracted=new, prior_extracted=prior,
            evidence_by_id=evidence, open_subquestion_ids={"sq-1"},
            verified_claims=[_claim("c1", "A brand new insight.")],
            claims_before=1, corroborated=0, confidence=0.5, gaps_open=1,
        )
        self.assertEqual(record.novelty, 0.5)
        self.assertEqual(document.novelty_score, 0.5)
        self.assertEqual(document.redundancy_score, 0.5)
        self.assertEqual(document.coverage_score, 1.0)
        self.assertGreater(document.evidence_density, 0.0)

    def test_iteration_with_no_new_claims_has_zero_gain(self):
        record = InformationGainAnalyzer().analyze(
            iteration=2, search_tasks=1,
            new_documents=[], new_extracted=[], prior_extracted=[],
            evidence_by_id={}, open_subquestion_ids=set(),
            verified_claims=[_claim("c1", "Old knowledge.")],
            claims_before=1, corroborated=0, confidence=0.5, gaps_open=0,
        )
        self.assertEqual(record.novelty, 0.0)
        self.assertEqual(record.knowledge_gain, 0.0)

    def test_fully_redundant_document_is_flagged(self):
        document = self._document()
        record = InformationGainAnalyzer().analyze(
            iteration=1, search_tasks=1,
            new_documents=[document], new_extracted=[], prior_extracted=[],
            evidence_by_id={}, open_subquestion_ids=set(),
            verified_claims=[], claims_before=0, corroborated=0,
            confidence=0.0, gaps_open=0,
        )
        self.assertEqual(document.redundancy_score, 1.0)
        self.assertEqual(record.knowledge_gain, 0.0)


class CuriosityTests(unittest.TestCase):
    def _discover(self, claims, contradictions=None, entities=None,
                  sources=None, plan=None, active=None):
        plan = plan or _plan()
        return CuriosityEngine().discover(
            plan=plan,
            claims=claims,
            contradictions=contradictions or [],
            entities=entities or [],
            sources=sources or {},
            active_subquestion_ids=active
            if active is not None
            else {sq.id for sq in plan.subquestions},
        )

    def test_unanswered_subquestion_becomes_missing_evidence_gap(self):
        gaps = self._discover(claims=[])
        kinds = [g.kind for g in gaps]
        self.assertIn(GapKind.MISSING_EVIDENCE, kinds)
        gap = gaps[kinds.index(GapKind.MISSING_EVIDENCE)]
        self.assertTrue(gap.suggested_query)
        self.assertEqual(gap.subquestion_id, "sq-1")

    def test_single_source_subquestion_becomes_uncorroborated_gap(self):
        gaps = self._discover(claims=[_claim("c1", "Fact.", sources=1)])
        self.assertIn(GapKind.UNCORROBORATED, [g.kind for g in gaps])

    def test_undefined_central_entity_becomes_definition_gap(self):
        claims = [
            _claim(f"c{i}", f"Statement {i} about the inverter.",
                   entities=["Inverter"], sources=2)
            for i in range(1, 4)
        ]
        entity = Entity(id="e1", name="Inverter",
                        claim_ids=[c.id for c in claims])
        gaps = self._discover(claims=claims, entities=[entity])
        definition_gaps = [
            g for g in gaps if g.kind is GapKind.MISSING_DEFINITION
        ]
        self.assertEqual(len(definition_gaps), 1)
        self.assertEqual(definition_gaps[0].entity, "Inverter")
        self.assertIn("Inverter", definition_gaps[0].suggested_query)

    def test_contradiction_becomes_gap(self):
        claims = [_claim("c1", "X is true.", sources=2)]
        contradiction = Contradiction(id="contra-1", description="X vs not-X",
                                      claim_ids=["c1"])
        gaps = self._discover(claims=claims, contradictions=[contradiction])
        self.assertIn(GapKind.CONTRADICTION, [g.kind for g in gaps])

    def test_important_low_authority_claim_needs_primary_source(self):
        claim = _claim("c1", "Crucial finding.", sources=1, importance=0.9)
        sources = {"src-1": Source(id="src-1", title="blog", provider="p",
                                   authority=0.2)}
        gaps = self._discover(claims=[claim], sources=sources)
        self.assertIn(GapKind.MISSING_PRIMARY_SOURCE, [g.kind for g in gaps])

    def test_inactive_subquestions_produce_no_gaps(self):
        gaps = self._discover(claims=[], active=set())
        self.assertEqual(
            [g for g in gaps if g.kind is GapKind.MISSING_EVIDENCE], []
        )


class StoppingTests(unittest.TestCase):
    def _state_with(self, records, gaps=0):
        state = ResearchState(
            session_id="s", request=ResearchRequest(topic="t"),
            plan=_plan(), tasks=[],
        )
        for record in records:
            state.record_iteration(record)
        state.add_gaps([
            KnowledgeGapFactory.make(i) for i in range(gaps)
        ])
        return state

    def _engine(self, **overrides):
        params = dict(
            confidence_threshold=0.7,
            min_iteration_gain=0.05,
            min_confidence_delta=0.02,
            max_iterations=3,
        )
        params.update(overrides)
        return StoppingEngine(**params)

    def test_stops_when_confidence_target_reached(self):
        state = self._state_with(
            [IterationRecord(iteration=1, confidence=0.75)], gaps=2
        )
        decision = self._engine().decide(state)
        self.assertTrue(decision.stop)
        self.assertIn("target", decision.reason)

    def test_stops_when_no_gaps_remain(self):
        state = self._state_with(
            [IterationRecord(iteration=1, confidence=0.3, knowledge_gain=0.5)]
        )
        decision = self._engine().decide(state)
        self.assertTrue(decision.stop)
        self.assertIn("gaps", decision.reason)

    def test_stops_when_budget_exhausted(self):
        records = [
            IterationRecord(iteration=i, confidence=0.2 + i * 0.1,
                            knowledge_gain=0.5)
            for i in range(1, 4)
        ]
        state = self._state_with(records, gaps=2)
        decision = self._engine().decide(state)
        self.assertTrue(decision.stop)
        self.assertIn("budget", decision.reason)

    def test_stops_when_gain_becomes_negligible(self):
        records = [
            IterationRecord(iteration=1, confidence=0.3, knowledge_gain=0.5),
            IterationRecord(iteration=2, confidence=0.4, knowledge_gain=0.01),
        ]
        state = self._state_with(records, gaps=2)
        decision = self._engine().decide(state)
        self.assertTrue(decision.stop)
        self.assertIn("gain", decision.reason)

    def test_stops_when_confidence_stabilizes(self):
        records = [
            IterationRecord(iteration=1, confidence=0.50, knowledge_gain=0.5),
            IterationRecord(iteration=2, confidence=0.505, knowledge_gain=0.3),
        ]
        state = self._state_with(records, gaps=2)
        decision = self._engine().decide(state)
        self.assertTrue(decision.stop)
        self.assertIn("stabilized", decision.reason)

    def test_continues_while_learning(self):
        records = [
            IterationRecord(iteration=1, confidence=0.3, knowledge_gain=0.6),
            IterationRecord(iteration=2, confidence=0.5, knowledge_gain=0.3),
        ]
        state = self._state_with(records, gaps=2)
        decision = self._engine().decide(state)
        self.assertFalse(decision.stop)
        self.assertIn("open knowledge gap", decision.reason)


class KnowledgeGapFactory:
    """Distinct gaps for stopping tests (state de-duplicates by identity)."""

    @staticmethod
    def make(index):
        from research_engine.domain.models import KnowledgeGap
        return KnowledgeGap(
            id="", kind=GapKind.MISSING_DEFINITION,
            description=f"gap {index}", suggested_query=f"q {index}",
            entity=f"entity-{index}", priority=0.5,
        )


if __name__ == "__main__":
    unittest.main()
