import json
import unittest

from tests import _path  # noqa: F401

from research_engine.domain.models import ClaimType, Evidence, RawDocument, Source
from research_engine.processing.extraction import (
    HeuristicClaimExtractor,
    LLMClaimExtractor,
    build_extractor,
    classify_claim,
)
from research_engine.providers.base import LLMProvider


def _doc(content="Solar power grew in 2023. It is clean."):
    return RawDocument(
        id="doc-1",
        query="q",
        task_id="collect-1",
        title="Solar",
        content=content,
        source=Source(id="src-1", title="t", provider="p"),
    )


def _evidence(passage, evidence_id="ev-1"):
    return Evidence(
        id=evidence_id, passage=passage, document_id="doc-1", source_id="src-1",
        subquestion_id="sq-1",
    )


class ClassifyClaimTests(unittest.TestCase):
    def test_types_are_classified_deterministically(self):
        cases = {
            "What remains unknown about qubit decoherence?": ClaimType.OPEN_QUESTION,
            "Quantum computing is defined as computation with qubits.": ClaimType.DEFINITION,
            "The model assumes ideal gas behavior.": ClaimType.ASSUMPTION,
            "A known limitation is decoherence noise.": ClaimType.LIMITATION,
            "The standard method uses error-correcting codes.": ClaimType.METHOD,
            "The transformer architecture was introduced in 2017.": ClaimType.DATE,
            "The system achieves 45% efficiency.": ClaimType.NUMERICAL,
            "Solar power is popular across many regions.": ClaimType.FACT,
        }
        for text, expected in cases.items():
            self.assertEqual(classify_claim(text), expected, msg=text)


class HeuristicExtractorTests(unittest.TestCase):
    def test_extracts_typed_claims_per_sentence_with_provenance(self):
        extractor = HeuristicClaimExtractor(["solar"])
        evidence = _evidence("Solar power grew 12% in 2023. Solar Energy is clean.")
        claims = extractor.extract(_doc(), [evidence])
        self.assertEqual(len(claims), 2)
        self.assertEqual(claims[0].claim_type, ClaimType.DATE)  # year outranks number
        self.assertTrue(all(c.evidence_id == "ev-1" for c in claims))
        self.assertIn("Solar Energy", claims[1].entities)


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
        return self._responses.pop(0) if self._responses else None


class LLMExtractorTests(unittest.TestCase):
    def _payload(self):
        return json.dumps(
            {
                "claims": [
                    {
                        "claim": "Solar capacity grew 12% in 2023.",
                        "type": "numerical",
                        "entities": ["Solar capacity"],
                        "passage": 1,
                    },
                    {
                        "claim": "Solar power is a renewable energy source.",
                        "type": "definition",
                        "entities": ["Solar power"],
                        "passage": 0,
                    },
                ]
            }
        )

    def test_parses_typed_claims_and_maps_passages(self):
        llm = _StubLLM([self._payload()])
        extractor = LLMClaimExtractor(
            llm, "solar", fallback=HeuristicClaimExtractor()
        )
        evidence = [_evidence("First passage.", "ev-1"), _evidence("Second.", "ev-2")]
        claims = extractor.extract(_doc(), evidence)
        self.assertEqual(len(claims), 2)
        self.assertEqual(claims[0].claim_type, ClaimType.NUMERICAL)
        self.assertEqual(claims[0].evidence_id, "ev-2")  # passage index 1
        self.assertEqual(claims[1].evidence_id, "ev-1")

    def test_parses_fenced_json(self):
        fenced = "```json\n" + self._payload() + "\n```"
        llm = _StubLLM([fenced])
        extractor = LLMClaimExtractor(llm, "solar", fallback=HeuristicClaimExtractor())
        claims = extractor.extract(_doc(), [_evidence("p")])
        self.assertEqual(len(claims), 2)

    def test_unknown_type_defaults_to_fact(self):
        payload = json.dumps(
            {"claims": [{"claim": "X happened.", "type": "banana", "passage": 0}]}
        )
        llm = _StubLLM([payload])
        extractor = LLMClaimExtractor(llm, "solar", fallback=HeuristicClaimExtractor())
        claims = extractor.extract(_doc(), [_evidence("p")])
        self.assertEqual(claims[0].claim_type, ClaimType.FACT)

    def test_retries_then_falls_back_to_heuristic(self):
        llm = _StubLLM(["garbage", "more garbage"])
        extractor = LLMClaimExtractor(
            llm, "solar", fallback=HeuristicClaimExtractor(), attempts=2
        )
        claims = extractor.extract(_doc(), [_evidence("Solar is clean.")])
        self.assertEqual(llm.calls, 2)
        self.assertTrue(claims)  # heuristic fallback still produced claims

    def test_retries_then_succeeds(self):
        llm = _StubLLM(["garbage", self._payload()])
        extractor = LLMClaimExtractor(
            llm, "solar", fallback=HeuristicClaimExtractor(), attempts=2
        )
        claims = extractor.extract(_doc(), [_evidence("p1"), _evidence("p2", "ev-2")])
        self.assertEqual(len(claims), 2)


class BuildExtractorTests(unittest.TestCase):
    def test_prefers_llm_when_available(self):
        extractor = build_extractor(_StubLLM([]), "topic")
        self.assertIsInstance(extractor, LLMClaimExtractor)

    def test_heuristic_when_disabled_or_missing(self):
        self.assertIsInstance(
            build_extractor(None, "topic"), HeuristicClaimExtractor
        )
        self.assertIsInstance(
            build_extractor(_StubLLM([]), "topic", enabled=False),
            HeuristicClaimExtractor,
        )


if __name__ == "__main__":
    unittest.main()
