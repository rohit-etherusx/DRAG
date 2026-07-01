import unittest

from tests import _path  # noqa: F401

from research_engine.domain.models import Evidence, RawDocument, Source
from research_engine.processing.processor import EvidenceProcessor


def _doc(doc_id, content, task_id="collect-1", source_id="src-1"):
    return RawDocument(
        id=doc_id,
        query="q",
        task_id=task_id,
        title="t",
        content=content,
        source=Source(id=source_id, title="t", provider="test"),
    )


class ProcessingTests(unittest.TestCase):
    def test_splits_claims_and_records_provenance(self):
        processor = EvidenceProcessor()
        evidence = processor.process([
            _doc("d1", "Alpha is real. Beta follows Alpha.")
        ])
        self.assertEqual(len(evidence), 2)
        for item in evidence:
            self.assertEqual(item.source_id, "src-1")
            self.assertEqual(item.task_id, "collect-1")

    def test_deduplicates_identical_claims(self):
        processor = EvidenceProcessor()
        evidence = processor.process([
            _doc("d1", "The sky is blue.", source_id="src-1"),
            _doc("d2", "The sky is blue.", source_id="src-2"),
        ])
        self.assertEqual(len(evidence), 1)

    def test_extracts_entities(self):
        processor = EvidenceProcessor(topic_keywords=["photosynthesis"])
        evidence = processor.process([
            _doc("d1", "Quantum Computing uses Superposition heavily.")
        ])
        names = {n for item in evidence for n in item.entities}
        self.assertIn("Quantum Computing", names)
        self.assertIn("Superposition", names)

    def test_detects_negation_contradiction(self):
        processor = EvidenceProcessor()
        evidence = [
            Evidence(id="ev-1", claim="Vaccines cause strong immune responses",
                     source_id="src-1", task_id="t"),
            Evidence(id="ev-2", claim="Vaccines do not cause strong immune responses",
                     source_id="src-2", task_id="t"),
        ]
        contradictions = processor.detect_contradictions(evidence)
        self.assertEqual(len(contradictions), 1)
        self.assertCountEqual(contradictions[0].evidence_ids, ["ev-1", "ev-2"])

    def test_no_false_contradiction(self):
        processor = EvidenceProcessor()
        evidence = [
            Evidence(id="ev-1", claim="Cats are mammals", source_id="s", task_id="t"),
            Evidence(id="ev-2", claim="Dogs are mammals", source_id="s", task_id="t"),
        ]
        self.assertEqual(processor.detect_contradictions(evidence), [])


if __name__ == "__main__":
    unittest.main()
