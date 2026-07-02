import unittest

from tests import _path  # noqa: F401

from research_engine.domain.models import ClaimType, Evidence, RawDocument, Source
from research_engine.processing.extraction import (
    ExtractedClaim,
    HeuristicClaimExtractor,
)
from research_engine.processing.normalizer import ClaimNormalizer
from research_engine.processing.processor import EvidenceProcessor
from research_engine.ranking.passages import PassageSelector


def _doc(doc_id, content, source_id="src-1", subquestion_id="sq-1"):
    return RawDocument(
        id=doc_id,
        query="solar energy",
        task_id="collect-1",
        title="Solar",
        content=content,
        source=Source(id=source_id, title="t", provider="p"),
        subquestion_id=subquestion_id,
        relevance_score=0.8,
    )


class EvidenceProcessorTests(unittest.TestCase):
    def setUp(self):
        self.processor = EvidenceProcessor(
            extractor=HeuristicClaimExtractor(),
            selector=PassageSelector(),
        )

    def test_produces_evidence_with_provenance_and_claims(self):
        documents = [_doc("doc-1", "Solar energy is defined as power from sunlight.")]
        evidence, claims = self.processor.process(documents, "What is solar energy?")
        self.assertEqual(len(evidence), 1)
        item = evidence[0]
        self.assertEqual(item.document_id, "doc-1")
        self.assertEqual(item.source_id, "src-1")
        self.assertEqual(item.subquestion_id, "sq-1")
        self.assertTrue(claims)
        self.assertEqual(claims[0].evidence_id, item.id)
        self.assertEqual(claims[0].claim_type, ClaimType.DEFINITION)

    def test_duplicate_passages_are_deduplicated_globally(self):
        content = "Solar energy is power from sunlight."
        evidence1, _ = self.processor.process(
            [_doc("doc-1", content)], "solar energy"
        )
        evidence2, _ = self.processor.process(
            [_doc("doc-2", content, source_id="src-2")], "solar energy"
        )
        self.assertEqual(len(evidence1), 1)
        self.assertEqual(evidence2, [])  # same passage, already seen

    def test_evidence_ids_are_sequential(self):
        documents = [
            _doc("doc-1", "Solar energy powers homes."),
            _doc("doc-2", "Wind energy also powers homes at solar scale."),
        ]
        evidence, _ = self.processor.process(documents, "energy")
        self.assertEqual([e.id for e in evidence], ["ev-1", "ev-2"])


def _extracted(text, evidence_id="ev-1", claim_type=ClaimType.FACT, entities=None):
    return ExtractedClaim(
        text=text, claim_type=claim_type, entities=entities or [],
        evidence_id=evidence_id,
    )


def _evidence(evidence_id, source_id="src-1", subquestion_id="sq-1"):
    return Evidence(
        id=evidence_id, passage="p", document_id="doc-1", source_id=source_id,
        subquestion_id=subquestion_id,
    )


class ClaimNormalizerTests(unittest.TestCase):
    def setUp(self):
        self.normalizer = ClaimNormalizer()

    def test_equivalent_wordings_merge_into_one_canonical_claim(self):
        evidence = {
            "ev-1": _evidence("ev-1", source_id="src-1"),
            "ev-2": _evidence("ev-2", source_id="src-2"),
        }
        extracted = [
            _extracted("Transformers were introduced in 2017.", "ev-1"),
            _extracted("In 2017, transformers were introduced.", "ev-2"),
        ]
        claims = self.normalizer.normalize(extracted, evidence)
        self.assertEqual(len(claims), 1)
        claim = claims[0]
        self.assertEqual(claim.id, "claim-1")
        # Both wordings preserved: one canonical, one variant.
        self.assertEqual(len(claim.variants), 1)
        # Provenance from both sources is unioned.
        self.assertEqual(claim.evidence_ids, ["ev-1", "ev-2"])
        self.assertEqual(claim.source_ids, ["src-1", "src-2"])

    def test_distinct_claims_stay_separate(self):
        evidence = {"ev-1": _evidence("ev-1")}
        extracted = [
            _extracted("Solar power is renewable.", "ev-1"),
            _extracted("Wind turbines require maintenance.", "ev-1"),
        ]
        claims = self.normalizer.normalize(extracted, evidence)
        self.assertEqual(len(claims), 2)

    def test_specific_type_wins_over_fact(self):
        evidence = {"ev-1": _evidence("ev-1"), "ev-2": _evidence("ev-2")}
        extracted = [
            _extracted("The model was released in 2020.", "ev-1", ClaimType.FACT),
            _extracted("The model was released in 2020.", "ev-2", ClaimType.DATE),
        ]
        claims = self.normalizer.normalize(extracted, evidence)
        self.assertEqual(claims[0].claim_type, ClaimType.DATE)

    def test_entities_are_unioned(self):
        evidence = {"ev-1": _evidence("ev-1")}
        extracted = [
            _extracted("Solar grew fast.", "ev-1", entities=["Solar"]),
            _extracted("Solar grew fast.", "ev-1", entities=["Growth"]),
        ]
        claims = self.normalizer.normalize(extracted, evidence)
        self.assertEqual(claims[0].entities, ["Solar", "Growth"])

    def test_normalization_is_deterministic(self):
        evidence = {"ev-1": _evidence("ev-1")}
        extracted = [
            _extracted("Alpha beta gamma.", "ev-1"),
            _extracted("Delta epsilon zeta.", "ev-1"),
        ]
        c1 = self.normalizer.normalize(extracted, evidence)
        c2 = ClaimNormalizer().normalize(extracted, evidence)
        self.assertEqual([c.text for c in c1], [c.text for c in c2])
        self.assertEqual([c.id for c in c1], [c.id for c in c2])


if __name__ == "__main__":
    unittest.main()
