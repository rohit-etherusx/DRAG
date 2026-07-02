import unittest

from tests import _path  # noqa: F401

from research_engine.domain.models import ResearchPlan, SearchCandidate, Source
from research_engine.ranking.authority import (
    ENCYCLOPEDIA,
    PRIMARY,
    SourceAuthorityScorer,
)
from research_engine.ranking.evaluator import CandidateEvaluator
from research_engine.ranking.passages import PassageSelector


class AuthorityScorerTests(unittest.TestCase):
    def setUp(self):
        self.scorer = SourceAuthorityScorer()

    def _source(self, locator, provider="web"):
        return Source(id="s", title="t", provider=provider, locator=locator)

    def test_known_domains_map_to_tiers(self):
        score, tier, domain = self.scorer.score(
            self._source("https://arxiv.org/abs/1234")
        )
        self.assertEqual((score, tier), (PRIMARY.score, PRIMARY.name))
        self.assertEqual(domain, "arxiv.org")

        score, tier, _ = self.scorer.score(
            self._source("https://en.wikipedia.org/wiki/X")
        )
        self.assertEqual((score, tier), (ENCYCLOPEDIA.score, ENCYCLOPEDIA.name))

    def test_tld_heuristics(self):
        _, tier, _ = self.scorer.score(self._source("https://www.nasa.gov/x"))
        self.assertEqual(tier, "official")
        _, tier, _ = self.scorer.score(self._source("https://cs.stanford.edu/x"))
        self.assertEqual(tier, "educational")

    def test_provider_fallback_without_domain(self):
        _, tier, domain = self.scorer.score(
            self._source("local://query/0", provider="local-knowledge (offline heuristic)")
        )
        self.assertEqual(domain, "")
        self.assertEqual(tier, "synthetic (offline)")

    def test_score_url_scores_bare_urls(self):
        score, tier, domain = self.scorer.score_url(
            "https://arxiv.org/abs/1", "arxiv"
        )
        self.assertEqual(tier, PRIMARY.name)
        self.assertEqual(domain, "arxiv.org")


def _candidate(url, title, snippet, provider="web"):
    return SearchCandidate(
        id=f"cand-{url}", query="q", title=title, snippet=snippet, url=url,
        provider=provider,
    )


def _plan(**overrides):
    defaults = dict(
        objective="Understand solar energy storage",
        question="solar energy storage",
        subject="solar energy storage",
        expected_entities=["battery"],
        exclusion_criteria=[],
    )
    defaults.update(overrides)
    return ResearchPlan(**defaults)


class CandidateEvaluatorTests(unittest.TestCase):
    def test_relevant_candidates_accepted_and_scored(self):
        evaluator = CandidateEvaluator(_plan(), max_accepted=3)
        candidates = [
            _candidate(
                "https://en.wikipedia.org/wiki/Solar",
                "Solar energy storage",
                "Batteries store solar energy for later use.",
            ),
            _candidate(
                "https://example.com/cats",
                "Cute cats compilation",
                "Cats doing funny things.",
            ),
        ]
        outcome = evaluator.evaluate(candidates, "How is solar energy stored?")
        self.assertEqual(len(outcome.accepted), 1)
        accepted = outcome.accepted[0]
        self.assertTrue(accepted.accepted)
        self.assertIn("wikipedia", accepted.url)
        self.assertGreater(accepted.relevance_score, 0.15)
        self.assertEqual(accepted.authority_tier, ENCYCLOPEDIA.name)

        rejected = outcome.rejected[0]
        self.assertFalse(rejected.accepted)
        self.assertIn("relevance", rejected.rejection_reason)

    def test_exclusion_criteria_reject_from_metadata(self):
        evaluator = CandidateEvaluator(
            _plan(exclusion_criteria=["stock price"]), max_accepted=3
        )
        candidates = [
            _candidate(
                "https://finance.example.com",
                "Solar energy stock price soars",
                "Solar storage battery energy shares rally.",
            )
        ]
        outcome = evaluator.evaluate(candidates, "solar energy storage")
        self.assertEqual(outcome.accepted, [])
        self.assertIn("exclusion", outcome.rejected[0].rejection_reason)

    def test_duplicate_titles_are_rejected(self):
        evaluator = CandidateEvaluator(_plan(), max_accepted=5)
        candidates = [
            _candidate("https://a.com/1", "Solar energy storage",
                       "Battery storage of solar energy."),
            _candidate("https://b.com/2", "Solar energy storage",
                       "Battery storage of solar energy."),
        ]
        outcome = evaluator.evaluate(candidates, "solar energy storage")
        self.assertEqual(len(outcome.accepted), 1)
        self.assertEqual(outcome.rejected[0].rejection_reason, "duplicate title")

    def test_budget_keeps_most_relevant_first(self):
        evaluator = CandidateEvaluator(_plan(), max_accepted=1)
        weaker = _candidate("https://a.com/1", "Solar panels",
                            "Solar energy overview.")
        stronger = _candidate("https://b.com/2", "Solar energy storage battery",
                              "How battery systems store solar energy.")
        outcome = evaluator.evaluate([weaker, stronger], "solar energy storage battery")
        self.assertEqual(len(outcome.accepted), 1)
        self.assertEqual(outcome.accepted[0].url, "https://b.com/2")
        self.assertIn("budget", outcome.rejected[0].rejection_reason)

    def test_disabled_gate_still_scores_but_accepts_all(self):
        evaluator = CandidateEvaluator(_plan(), enabled=False, max_accepted=5)
        candidates = [
            _candidate("https://example.com/cats", "Cats", "Cats being cats."),
        ]
        outcome = evaluator.evaluate(candidates, "solar energy storage")
        self.assertEqual(len(outcome.accepted), 1)
        # Scores are still stamped for the audit trail.
        self.assertEqual(candidates[0].authority_tier, "unknown web")

    def test_min_authority_gate(self):
        evaluator = CandidateEvaluator(_plan(), min_authority=0.5, max_accepted=5)
        low_authority = _candidate(
            "https://medium.com/post", "Solar energy storage",
            "Battery storage of solar energy explained.",
        )
        outcome = evaluator.evaluate([low_authority], "solar energy storage")
        self.assertEqual(outcome.accepted, [])
        self.assertIn("authority", outcome.rejected[0].rejection_reason)


class PassageSelectorTests(unittest.TestCase):
    def test_keeps_relevant_passages_in_order(self):
        content = (
            "Solar panels convert sunlight into electricity.\n\n"
            "Unrelated paragraph about medieval cooking recipes and kitchens.\n\n"
            "Batteries store solar electricity for later use."
        )
        selector = PassageSelector(max_passages=2, min_relevance=0.2)
        passages = selector.top_passages(content, "solar electricity batteries")
        texts = [p for p, _ in passages]
        self.assertEqual(len(texts), 2)
        self.assertIn("Solar panels", texts[0])
        self.assertIn("Batteries", texts[1])

    def test_fails_open_when_nothing_qualifies(self):
        content = "One paragraph.\n\nAnother paragraph."
        selector = PassageSelector(min_relevance=0.99)
        passages = selector.top_passages(content, "completely unrelated terms")
        self.assertEqual(len(passages), 1)
        self.assertEqual(passages[0][0], content)

    def test_single_passage_returned_whole(self):
        selector = PassageSelector()
        passages = selector.top_passages("Short text about solar.", "solar")
        self.assertEqual(len(passages), 1)

    def test_empty_content(self):
        self.assertEqual(PassageSelector().top_passages("", "topic"), [])

    def test_select_concatenates(self):
        content = "About solar power.\n\nAbout solar batteries."
        out = PassageSelector().select(content, "solar")
        self.assertIn("solar power", out)
        self.assertIn("solar batteries", out)


if __name__ == "__main__":
    unittest.main()
