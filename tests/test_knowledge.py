import unittest

from tests import _path  # noqa: F401

from research_engine.domain.models import (
    Claim,
    ClaimType,
    EdgeRelation,
    Evidence,
)
from research_engine.knowledge.graph import EvidenceGraph


def _claim(cid, text, claim_type=ClaimType.FACT, entities=None,
           evidence_ids=None, contradicts=None, subquestion_ids=None):
    return Claim(
        id=cid, text=text, claim_type=claim_type, entities=entities or [],
        evidence_ids=evidence_ids or [], contradicts=contradicts or [],
        subquestion_ids=subquestion_ids or ["sq-1"],
    )


def _evidence(eid, document_id="doc-1"):
    return Evidence(
        id=eid, passage=f"passage {eid}", document_id=document_id,
        source_id="src-1",
    )


class EvidenceGraphTests(unittest.TestCase):
    def test_claims_are_primary_nodes_with_provenance_edges(self):
        graph = EvidenceGraph()
        graph.build(
            [_claim("claim-1", "Solar works.", evidence_ids=["ev-1"])],
            [_evidence("ev-1")],
        )
        kinds = {n.kind for n in graph.nodes}
        self.assertEqual(kinds, {"claim", "evidence", "document"})

        supports = graph.edges_by_relation(EdgeRelation.SUPPORTS)
        self.assertEqual(len(supports), 1)
        self.assertEqual(supports[0].source_id, "n-evidence-ev-1")
        self.assertEqual(supports[0].target_id, "n-claim-claim-1")

        references = graph.edges_by_relation(EdgeRelation.REFERENCES)
        self.assertTrue(
            any(e.target_id == "n-document-doc-1" for e in references)
        )

    def test_definition_claim_defines_its_first_entity(self):
        graph = EvidenceGraph()
        graph.build(
            [
                _claim(
                    "claim-1",
                    "Solar power is defined as energy from sunlight.",
                    claim_type=ClaimType.DEFINITION,
                    entities=["Solar power", "Sunlight"],
                )
            ],
            [],
        )
        defines = graph.edges_by_relation(EdgeRelation.DEFINES)
        self.assertEqual(len(defines), 1)
        self.assertEqual(defines[0].target_id, "n-entity-ent-solar-power")
        # The second entity is merely referenced.
        references = graph.edges_by_relation(EdgeRelation.REFERENCES)
        self.assertTrue(
            any(e.target_id == "n-entity-ent-sunlight" for e in references)
        )

    def test_contradiction_edges(self):
        graph = EvidenceGraph()
        graph.build(
            [
                _claim("claim-1", "X is true.", contradicts=["claim-2"]),
                _claim("claim-2", "X is not true.", contradicts=["claim-1"]),
            ],
            [],
        )
        contradicts = graph.edges_by_relation(EdgeRelation.CONTRADICTS)
        self.assertEqual(len(contradicts), 2)  # one directed edge per claim

    def test_detail_claim_extends_definition_via_shared_entity(self):
        graph = EvidenceGraph()
        graph.build(
            [
                _claim(
                    "claim-1",
                    "The transformer is defined as an attention-based model.",
                    claim_type=ClaimType.DEFINITION,
                    entities=["Transformer"],
                ),
                _claim(
                    "claim-2",
                    "The transformer was introduced in 2017.",
                    claim_type=ClaimType.DATE,
                    entities=["Transformer"],
                ),
            ],
            [],
        )
        extends = graph.edges_by_relation(EdgeRelation.EXTENDS)
        self.assertEqual(len(extends), 1)
        self.assertEqual(extends[0].source_id, "n-claim-claim-2")
        self.assertEqual(extends[0].target_id, "n-claim-claim-1")

    def test_method_depends_on_assumption(self):
        graph = EvidenceGraph()
        graph.build(
            [
                _claim(
                    "claim-1", "The method uses Monte Carlo sampling.",
                    claim_type=ClaimType.METHOD, entities=["Monte Carlo"],
                ),
                _claim(
                    "claim-2", "The approach assumes Monte Carlo convergence.",
                    claim_type=ClaimType.ASSUMPTION, entities=["Monte Carlo"],
                ),
            ],
            [],
        )
        depends = graph.edges_by_relation(EdgeRelation.DEPENDS_ON)
        self.assertEqual(len(depends), 1)
        self.assertEqual(depends[0].source_id, "n-claim-claim-1")

    def test_central_entities_and_claims_for_entity(self):
        graph = EvidenceGraph()
        graph.build(
            [
                _claim("claim-1", "A.", entities=["Solar"]),
                _claim("claim-2", "B.", entities=["Solar", "Wind"]),
                _claim("claim-3", "C.", entities=["Wind"]),
                _claim("claim-4", "D.", entities=["Solar"]),
            ],
            [],
        )
        central = graph.central_entities(1)
        self.assertEqual(central[0].name, "Solar")
        self.assertEqual(len(graph.claims_for_entity("Solar")), 3)
        self.assertEqual(graph.claims_for_entity("Unknown"), [])

    def test_graph_is_deterministic(self):
        def build():
            graph = EvidenceGraph()
            graph.build(
                [
                    _claim("claim-1", "A.", entities=["Solar"], evidence_ids=["ev-1"]),
                    _claim("claim-2", "B.", entities=["Wind"], evidence_ids=["ev-2"]),
                ],
                [_evidence("ev-1"), _evidence("ev-2", document_id="doc-2")],
            )
            return (
                [(n.id, n.kind) for n in graph.nodes],
                [(e.source_id, e.target_id, e.relation) for e in graph.edges],
            )

        self.assertEqual(build(), build())


if __name__ == "__main__":
    unittest.main()
