import unittest

from tests import _path  # noqa: F401

from research_engine.config import EngineConfig
from research_engine.domain.models import RawDocument, Source
from research_engine.ranking.authority import (
    ENCYCLOPEDIA,
    PRIMARY,
    SourceAuthorityScorer,
)
from research_engine.ranking.passages import PassageSelector
from research_engine.ranking.ranker import build_ranker
from research_engine.ranking.relevance import HeuristicRelevanceScorer, _parse_score


def _doc(content, title="t", query="quantum computing", url="", provider="test"):
    return RawDocument(
        id="d1",
        query=query,
        task_id="collect-1",
        title=title,
        content=content,
        source=Source(id="src-1", title=title, provider=provider, locator=url),
    )


class AuthorityTests(unittest.TestCase):
    def setUp(self):
        self.scorer = SourceAuthorityScorer()

    def test_arxiv_domain_is_primary(self):
        s = Source(id="s", title="t", provider="arxiv", locator="https://arxiv.org/abs/1234")
        score, tier, domain = self.scorer.score(s)
        self.assertEqual(tier, PRIMARY.name)
        self.assertEqual(domain, "arxiv.org")
        self.assertAlmostEqual(score, PRIMARY.score)

    def test_wikipedia_subdomain_is_encyclopedia(self):
        s = Source(id="s", title="t", provider="wikipedia", locator="https://en.wikipedia.org/wiki/X")
        _, tier, domain = self.scorer.score(s)
        self.assertEqual(tier, ENCYCLOPEDIA.name)
        self.assertEqual(domain, "en.wikipedia.org")

    def test_gov_and_edu_tlds(self):
        gov = Source(id="s", title="t", provider="web", locator="https://nasa.gov/page")
        edu = Source(id="s", title="t", provider="web", locator="https://mit.edu/page")
        self.assertEqual(self.scorer.score(gov)[1], "official")
        self.assertEqual(self.scorer.score(edu)[1], "educational")

    def test_personal_blog_platform(self):
        s = Source(id="s", title="t", provider="web", locator="https://someone.medium.com/post")
        self.assertEqual(self.scorer.score(s)[1], "personal blog")

    def test_provider_fallback_when_no_domain(self):
        # Offline provider produces local:// locators with no network domain.
        s = Source(id="s", title="t", provider="local-knowledge (offline heuristic)", locator="local://x/0")
        score, tier, domain = self.scorer.score(s)
        self.assertEqual(domain, "")
        self.assertEqual(tier, "synthetic (offline)")

    def test_scoring_does_not_mutate_source(self):
        s = Source(id="s", title="t", provider="arxiv", locator="https://arxiv.org/abs/1")
        self.scorer.score(s)
        self.assertEqual(s.authority, 0.0)  # unchanged; the ranker stamps it


class RelevanceTests(unittest.TestCase):
    def test_relevant_document_scores_higher_than_irrelevant(self):
        scorer = HeuristicRelevanceScorer(["quantum", "computing"])
        relevant = _doc("Quantum computing uses qubits for quantum computation.")
        irrelevant = _doc("The recipe calls for flour, sugar, and butter.")
        self.assertGreater(
            scorer.score(relevant, "quantum computing"),
            scorer.score(irrelevant, "quantum computing"),
        )

    def test_title_match_contributes(self):
        scorer = HeuristicRelevanceScorer(["quantum", "computing"])
        with_title = _doc("Some body text.", title="Quantum Computing overview")
        without = _doc("Some body text.", title="Unrelated heading")
        self.assertGreater(
            scorer.score(with_title, "quantum computing"),
            scorer.score(without, "quantum computing"),
        )

    def test_no_terms_fails_open(self):
        scorer = HeuristicRelevanceScorer([])
        self.assertEqual(scorer.score(_doc("anything", query=""), ""), 1.0)

    def test_parse_score_extracts_and_clamps(self):
        self.assertEqual(_parse_score("0.8"), 0.8)
        self.assertEqual(_parse_score("Relevance: 0.35 out of 1"), 0.35)
        self.assertEqual(_parse_score("1.0"), 1.0)
        self.assertIsNone(_parse_score("no number here"))
        self.assertIsNone(_parse_score(None))


class PassageTests(unittest.TestCase):
    def test_keeps_relevant_passage_drops_irrelevant(self):
        selector = PassageSelector(max_passages=1, min_relevance=0.01)
        content = (
            "Quantum computing relies on qubits and superposition.\n\n"
            "Unrelated paragraph about gardening and tomatoes."
        )
        result = selector.select(content, "quantum computing")
        self.assertIn("qubits", result)
        self.assertNotIn("tomatoes", result)

    def test_fails_open_when_nothing_qualifies(self):
        selector = PassageSelector(max_passages=2, min_relevance=0.99)
        content = "Alpha beta gamma.\n\nDelta epsilon zeta."
        # No topic terms match => nothing qualifies => original content returned.
        self.assertEqual(selector.select(content, "quantum computing"), content)

    def test_single_passage_returned_as_is(self):
        selector = PassageSelector()
        self.assertEqual(selector.select("One sentence only.", "topic"), "One sentence only.")

    def test_preserves_original_order(self):
        selector = PassageSelector(max_passages=2, min_relevance=0.01)
        content = (
            "Quantum theory is foundational.\n\n"
            "Filler about nothing in particular.\n\n"
            "Quantum computing extends quantum theory."
        )
        result = selector.select(content, "quantum computing")
        self.assertLess(result.index("foundational"), result.index("extends"))


class RankerTests(unittest.TestCase):
    def _config(self, **overrides):
        cfg = EngineConfig()
        for k, v in overrides.items():
            setattr(cfg, k, v)
        return cfg

    def test_rejects_irrelevant_and_stamps_scores(self):
        ranker = build_ranker(
            self._config(relevance_threshold=0.2),
            "quantum computing",
            ["quantum", "computing"],
        )
        docs = [
            _doc("Quantum computing uses qubits for computation.", url="https://arxiv.org/abs/1"),
            _doc("A dessert recipe with flour and sugar.", url="https://cooking.example.com/x"),
        ]
        outcome = ranker.rank(docs)
        self.assertEqual(len(outcome.accepted), 1)
        self.assertEqual(outcome.rejected, 1)
        # Authority + relevance stamped on the originals (record keeping).
        self.assertEqual(docs[0].source.authority_tier, PRIMARY.name)
        self.assertGreater(docs[0].relevance_score, 0.0)

    def test_disabled_ranker_accepts_everything(self):
        ranker = build_ranker(
            self._config(ranking_enabled=False),
            "quantum computing",
            ["quantum", "computing"],
        )
        docs = [_doc("totally unrelated content about nothing")]
        outcome = ranker.rank(docs)
        self.assertEqual(len(outcome.accepted), 1)
        self.assertEqual(outcome.rejected, 0)

    def test_min_authority_gate(self):
        ranker = build_ranker(
            self._config(relevance_threshold=0.0, min_authority=0.9),
            "quantum computing",
            ["quantum", "computing"],
        )
        docs = [
            _doc("Quantum computing content.", url="https://arxiv.org/abs/1"),  # PRIMARY 0.95
            _doc("Quantum computing content.", url="https://random.example.com/x"),  # unknown 0.40
        ]
        outcome = ranker.rank(docs)
        self.assertEqual(len(outcome.accepted), 1)
        self.assertEqual(outcome.accepted[0].source.locator, "https://arxiv.org/abs/1")


if __name__ == "__main__":
    unittest.main()
