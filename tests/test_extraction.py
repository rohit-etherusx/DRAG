import unittest

from tests import _path  # noqa: F401

from research_engine.domain.models import RawDocument, Source
from research_engine.processing.extraction import (
    HeuristicClaimExtractor,
    LLMClaimExtractor,
    build_extractor,
)
from research_engine.providers.base import LLMProvider


class _FakeLLM(LLMProvider):
    name = "fake"

    def __init__(self, response, available=True):
        self._response = response
        self._available = available

    @property
    def available(self):
        return self._available

    def generate(self, prompt, system=None):
        return self._response


class _SequencedLLM(LLMProvider):
    name = "sequenced"

    def __init__(self, responses):
        self._responses = responses
        self.calls = 0

    @property
    def available(self):
        return True

    def generate(self, prompt, system=None):
        response = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        return response


def _doc(content="Alpha is real. Beta follows Alpha."):
    return RawDocument(
        id="d1",
        query="q",
        task_id="collect-1",
        title="Title",
        content=content,
        source=Source(id="src-1", title="t", provider="test"),
    )


class HeuristicExtractorTests(unittest.TestCase):
    def test_splits_sentences(self):
        result = HeuristicClaimExtractor().extract(_doc())
        self.assertEqual(len(result.claims), 2)
        self.assertEqual(result.claims[0].text, "Alpha is real.")
        self.assertEqual(result.relationships, [])


class LLMExtractorTests(unittest.TestCase):
    def test_parses_claims_and_relationships(self):
        response = (
            'Here you go: {"claims": [{"claim": "Qubits enable superposition.", '
            '"entities": ["Qubits", "superposition"]}], '
            '"relationships": [{"source": "Qubits", "relation": "exhibit", '
            '"target": "superposition"}]} done'
        )
        extractor = LLMClaimExtractor(_FakeLLM(response), "quantum", HeuristicClaimExtractor())
        result = extractor.extract(_doc())
        self.assertEqual(len(result.claims), 1)
        self.assertEqual(result.claims[0].text, "Qubits enable superposition.")
        self.assertIn("Qubits", result.claims[0].entities)
        self.assertEqual(len(result.relationships), 1)
        self.assertEqual(result.relationships[0].relation, "exhibit")
        self.assertEqual(result.relationships[0].source, "Qubits")

    def test_falls_back_on_bad_json(self):
        extractor = LLMClaimExtractor(
            _FakeLLM("not json at all"), "topic", HeuristicClaimExtractor()
        )
        result = extractor.extract(_doc())
        # Fallback = heuristic sentence splitting -> 2 claims.
        self.assertEqual(len(result.claims), 2)

    def test_falls_back_when_unavailable(self):
        extractor = LLMClaimExtractor(
            _FakeLLM("{}", available=False), "topic", HeuristicClaimExtractor()
        )
        result = extractor.extract(_doc())
        self.assertEqual(len(result.claims), 2)

    def test_falls_back_when_no_claims(self):
        # Well-formed object but empty claims -> unusable -> heuristic fallback.
        extractor = LLMClaimExtractor(
            _FakeLLM('{"claims": [], "relationships": []}'), "t", HeuristicClaimExtractor()
        )
        result = extractor.extract(_doc())
        self.assertEqual(len(result.claims), 2)

    def test_non_list_entities_do_not_crash(self):
        response = '{"claims": [{"claim": "X happens.", "entities": "oops"}]}'
        extractor = LLMClaimExtractor(_FakeLLM(response), "t", HeuristicClaimExtractor())
        result = extractor.extract(_doc())
        self.assertEqual(len(result.claims), 1)
        self.assertEqual(result.claims[0].entities, [])

    def test_parses_fenced_json(self):
        response = (
            "```json\n"
            '{"claims": [{"claim": "Y is true.", "entities": ["Y"]}], '
            '"relationships": []}\n'
            "```"
        )
        extractor = LLMClaimExtractor(_FakeLLM(response), "t", HeuristicClaimExtractor())
        result = extractor.extract(_doc())
        self.assertEqual(len(result.claims), 1)
        self.assertEqual(result.claims[0].text, "Y is true.")

    def test_retries_then_succeeds(self):
        # First attempt unusable, second attempt valid -> LLM result (not fallback).
        seq = _SequencedLLM([
            "garbage",
            '{"claims": [{"claim": "Recovered.", "entities": []}], "relationships": []}',
        ])
        extractor = LLMClaimExtractor(seq, "t", HeuristicClaimExtractor(), attempts=2)
        result = extractor.extract(_doc())
        self.assertEqual(seq.calls, 2)
        self.assertEqual(len(result.claims), 1)
        self.assertEqual(result.claims[0].text, "Recovered.")

    def test_drops_self_referential_relationship(self):
        response = (
            '{"claims": [{"claim": "A relates to A.", "entities": ["A"]}], '
            '"relationships": [{"source": "A", "relation": "is", "target": "A"}]}'
        )
        extractor = LLMClaimExtractor(_FakeLLM(response), "t", HeuristicClaimExtractor())
        result = extractor.extract(_doc())
        self.assertEqual(result.relationships, [])


class BuildExtractorTests(unittest.TestCase):
    def test_selects_llm_when_available(self):
        extractor = build_extractor(_FakeLLM("[]"), "topic", enabled=True)
        self.assertIsInstance(extractor, LLMClaimExtractor)

    def test_heuristic_when_disabled(self):
        extractor = build_extractor(_FakeLLM("[]"), "topic", enabled=False)
        self.assertIsInstance(extractor, HeuristicClaimExtractor)

    def test_heuristic_when_no_llm(self):
        extractor = build_extractor(None, "topic", enabled=True)
        self.assertIsInstance(extractor, HeuristicClaimExtractor)


if __name__ == "__main__":
    unittest.main()
