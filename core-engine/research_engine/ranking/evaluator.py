"""Candidate evaluation — the pre-download gate.

Operates *only* on search-result metadata: title, snippet, URL, and source
provider (``OBJECTIVE.md`` module 3). No document content exists at this stage.
For each candidate it:

1. stamps deterministic source authority (domain/provider → tier + score);
2. scores topical relevance from the title and snippet against the
   subquestion, the plan's subject, and its expected entities;
3. rejects candidates matching the plan's exclusion criteria;
4. rejects candidates below the relevance (and optional authority) thresholds;
5. de-duplicates near-identical results;
6. prioritizes the survivors by relevance then authority, keeping the top N
   per subquestion.

Only accepted candidates are ever downloaded, which is what reduces bandwidth
and token consumption. Every candidate keeps its scores and, when rejected,
the reason — the full audit trail lands in the session record.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from research_engine.domain.models import ResearchPlan, SearchCandidate
from research_engine.logging_setup import get_logger
from research_engine.ranking.authority import SourceAuthorityScorer
from research_engine.utils import keywords, slugify

_log = get_logger("ranking.evaluator")

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9'\-]+")


@dataclass
class EvaluationOutcome:
    """Result of evaluating one batch of candidates."""

    accepted: list[SearchCandidate] = field(default_factory=list)
    rejected: list[SearchCandidate] = field(default_factory=list)


class CandidateEvaluator:
    """Accepts or rejects search candidates from metadata alone."""

    def __init__(
        self,
        plan: ResearchPlan,
        *,
        relevance_threshold: float = 0.15,
        min_authority: float = 0.0,
        max_accepted: int = 3,
        enabled: bool = True,
        authority_scorer: SourceAuthorityScorer | None = None,
    ) -> None:
        self._plan = plan
        self._relevance_threshold = relevance_threshold
        self._min_authority = min_authority
        self._max_accepted = max(1, max_accepted)
        self._enabled = enabled
        self._authority = authority_scorer or SourceAuthorityScorer()
        self._plan_terms = _terms(
            [plan.subject, plan.question] + list(plan.expected_entities)
        )
        self._exclusions = [term.lower() for term in plan.exclusion_criteria if term]

    def evaluate(
        self, candidates: list[SearchCandidate], subquestion_text: str
    ) -> EvaluationOutcome:
        """Score and gate ``candidates`` for one subquestion.

        Candidates are mutated in place (scores, accepted flag, rejection
        reason) so the session record carries the complete audit trail.
        """
        terms = self._plan_terms | _terms([subquestion_text])
        scored: list[SearchCandidate] = []
        rejected: list[SearchCandidate] = []
        seen_titles: set[str] = set()

        for candidate in candidates:
            authority, tier, domain = self._authority.score_url(
                candidate.url, candidate.provider
            )
            candidate.domain = domain
            candidate.authority = authority
            candidate.authority_tier = tier
            candidate.relevance_score = _relevance(candidate, terms)

            reason = self._rejection_reason(candidate, seen_titles)
            if reason:
                candidate.accepted = False
                candidate.rejection_reason = reason
                rejected.append(candidate)
                _log.debug("Rejected %s: %s", candidate.id, reason)
                continue
            seen_titles.add(slugify(candidate.title))
            scored.append(candidate)

        # Prioritize: most relevant first, authority as tiebreaker; keep top N.
        scored.sort(key=lambda c: (c.relevance_score, c.authority), reverse=True)
        accepted = scored[: self._max_accepted]
        for candidate in accepted:
            candidate.accepted = True
        for candidate in scored[self._max_accepted :]:
            candidate.accepted = False
            candidate.rejection_reason = "over per-subquestion budget"
            rejected.append(candidate)

        return EvaluationOutcome(accepted=accepted, rejected=rejected)

    def _rejection_reason(
        self, candidate: SearchCandidate, seen_titles: set[str]
    ) -> str:
        """Return why ``candidate`` must be rejected, or "" to keep it."""
        if not self._enabled:
            return ""
        metadata_text = f"{candidate.title} {candidate.snippet}".lower()
        for term in self._exclusions:
            if term in metadata_text:
                return f"matches exclusion criterion '{term}'"
        if slugify(candidate.title) in seen_titles:
            return "duplicate title"
        if candidate.relevance_score < self._relevance_threshold:
            return (
                f"relevance {candidate.relevance_score:.2f} below threshold "
                f"{self._relevance_threshold:.2f}"
            )
        if candidate.authority < self._min_authority:
            return (
                f"authority {candidate.authority:.2f} below minimum "
                f"{self._min_authority:.2f}"
            )
        return ""


def _terms(texts: list[str]) -> set[str]:
    terms: set[str] = set()
    for text in texts:
        terms.update(k.lower() for k in keywords(text or ""))
    return {t for t in terms if len(t) >= 3}


def _relevance(candidate: SearchCandidate, terms: set[str]) -> float:
    """Deterministic 0..1 relevance from title/snippet term coverage.

    The title is a stronger signal than the snippet, so it is weighted higher.
    Fails open (1.0) when there are no terms to match — never reject blindly.
    """
    if not terms:
        return 1.0
    title_tokens = set(_TOKEN_RE.findall(candidate.title.lower()))
    snippet_tokens = set(_TOKEN_RE.findall(candidate.snippet.lower()))
    combined = title_tokens | snippet_tokens

    coverage = sum(1 for t in terms if t in combined) / len(terms)
    title_cov = sum(1 for t in terms if t in title_tokens) / len(terms)
    return round(min(1.0, 0.7 * coverage + 0.3 * title_cov), 4)
