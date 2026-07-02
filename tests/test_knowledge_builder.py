import unittest

from tests import _path  # noqa: F401

from research_engine.domain.models import Claim, ClaimType, Evidence
from research_engine.knowledge.builder import KnowledgeBuilder


def _claim(cid, text, entities, claim_type=ClaimType.FACT):
    return Claim(
        id=cid, text=text, claim_type=claim_type, entities=list(entities),
        evidence_ids=[f"ev-{cid}"], source_ids=["src-1"],
        subquestion_ids=["sq-1"],
    )


def _evidence(claims):
    return [
        Evidence(id=f"ev-{c.id}", passage=c.text, document_id="doc-1",
                 source_id="src-1", subquestion_id="sq-1")
        for c in claims
    ]


class AliasMergingTests(unittest.TestCase):
    def test_case_and_plural_variants_merge_to_most_frequent_spelling(self):
        claims = [
            _claim("c1", "A.", ["Transformer"]),
            _claim("c2", "B.", ["Transformer"]),
            _claim("c3", "C.", ["transformers"]),
        ]
        graph = KnowledgeBuilder().build(claims, _evidence(claims))
        names = [e.name for e in graph.entities]
        self.assertEqual(names, ["Transformer"])
        # Claim entity lists were canonicalized in place.
        self.assertEqual(claims[2].entities, ["Transformer"])
        # The merged entity accumulates every claim's reference.
        self.assertEqual(
            set(graph.entities[0].claim_ids), {"c1", "c2", "c3"}
        )

    def test_distinct_entities_stay_distinct(self):
        claims = [
            _claim("c1", "A.", ["Encoder"]),
            _claim("c2", "B.", ["Decoder"]),
        ]
        graph = KnowledgeBuilder().build(claims, _evidence(claims))
        self.assertEqual(
            sorted(e.name for e in graph.entities), ["Decoder", "Encoder"]
        )

    def test_short_words_are_not_plural_folded(self):
        claims = [
            _claim("c1", "A.", ["GPS"]),
            _claim("c2", "B.", ["GP"]),
        ]
        graph = KnowledgeBuilder().build(claims, _evidence(claims))
        self.assertEqual(len(graph.entities), 2)

    def test_graph_is_rebuilt_from_claims_and_evidence(self):
        claims = [
            _claim("c1", "The encoder is a component.", ["Encoder"],
                   claim_type=ClaimType.DEFINITION),
        ]
        graph = KnowledgeBuilder().build(claims, _evidence(claims))
        kinds = {n.kind for n in graph.nodes}
        self.assertEqual(kinds, {"claim", "evidence", "document", "entity"})

    def test_build_is_deterministic(self):
        def run():
            claims = [
                _claim("c1", "A.", ["Transformers", "Encoder"]),
                _claim("c2", "B.", ["transformer"]),
            ]
            graph = KnowledgeBuilder().build(claims, _evidence(claims))
            return (
                [e.name for e in graph.entities],
                [(n.id, n.kind) for n in graph.nodes],
            )

        self.assertEqual(run(), run())


if __name__ == "__main__":
    unittest.main()
