import unittest

from tests import _path  # noqa: F401

from research_engine.domain.models import Evidence
from research_engine.knowledge.graph import KnowledgeGraph


class KnowledgeGraphTests(unittest.TestCase):
    def test_builds_entities_and_cooccurrence_relationships(self):
        graph = KnowledgeGraph()
        graph.build([
            Evidence(id="ev-1", claim="c", source_id="s", task_id="t",
                     entities=["Alpha", "Beta"]),
        ])
        names = {e.name for e in graph.entities}
        self.assertEqual(names, {"Alpha", "Beta"})
        self.assertEqual(len(graph.relationships), 1)

    def test_relationship_accumulates_evidence(self):
        graph = KnowledgeGraph()
        graph.build([
            Evidence(id="ev-1", claim="c", source_id="s", task_id="t",
                     entities=["Alpha", "Beta"]),
            Evidence(id="ev-2", claim="c", source_id="s", task_id="t",
                     entities=["Alpha", "Beta"]),
        ])
        self.assertEqual(len(graph.relationships), 1)
        self.assertEqual(len(graph.relationships[0].evidence_ids), 2)

    def test_neighbors(self):
        graph = KnowledgeGraph()
        graph.build([
            Evidence(id="ev-1", claim="c", source_id="s", task_id="t",
                     entities=["Alpha", "Beta"]),
        ])
        alpha = next(e for e in graph.entities if e.name == "Alpha")
        beta = next(e for e in graph.entities if e.name == "Beta")
        self.assertIn(beta.id, graph.neighbors(alpha.id))

    def test_single_entity_has_no_relationships(self):
        graph = KnowledgeGraph()
        graph.build([
            Evidence(id="ev-1", claim="c", source_id="s", task_id="t",
                     entities=["Solo"]),
        ])
        self.assertEqual(graph.relationships, [])

    def test_extracted_relationship_promotes_cooccurrence_label(self):
        graph = KnowledgeGraph()
        graph.build([
            Evidence(id="ev-1", claim="c", source_id="s", task_id="t",
                     entities=["Cas9", "DNA"]),
        ])
        # Co-occurrence created a generic related_to edge...
        self.assertEqual(graph.relationships[0].relation, "related_to")
        graph.add_extracted_relationships([("Cas9", "cuts", "DNA", ["ev-1"])])
        # ...which the extracted relation promotes, without duplicating the edge.
        self.assertEqual(len(graph.relationships), 1)
        self.assertEqual(graph.relationships[0].relation, "cuts")

    def test_extracted_relationship_creates_new_entities(self):
        graph = KnowledgeGraph()
        graph.add_extracted_relationships([("Doudna", "co-developed", "CRISPR", ["ev-9"])])
        names = {e.name for e in graph.entities}
        self.assertEqual(names, {"Doudna", "CRISPR"})
        self.assertEqual(len(graph.relationships), 1)
        self.assertEqual(graph.relationships[0].relation, "co-developed")

    def test_extracted_self_relationship_is_ignored(self):
        graph = KnowledgeGraph()
        graph.add_extracted_relationships([("X", "is", "X", ["ev-1"])])
        self.assertEqual(graph.relationships, [])


if __name__ == "__main__":
    unittest.main()
