"""Answer generation.

The answer — not the report — is the product of a research run
(``OBJECTIVE.md`` principle 1). Once the research loop has stopped, this
module synthesizes the final :class:`Answer` from the completed knowledge
model: the verified claims (importance-ranked), the session confidence, and
the open knowledge gaps. It never searches and never reads documents.

Question-shaped objectives get a direct answer; topic-shaped objectives get
the core understanding the knowledge model supports. Both cite the claims
they rest on, state their confidence, and name what remains uncertain — the
engine never papers over what it does not know.

An optional LLM phrases the answer (grounded strictly in the claims it is
given); the deterministic fallback concatenates the strongest claims, so the
engine answers end-to-end offline.
"""
from __future__ import annotations

from research_engine.domain.models import (
    Answer,
    Claim,
    ClaimType,
    ConfidenceReport,
    Finding,
    KnowledgeGap,
    ResearchPlan,
    VerificationStatus,
)
from research_engine.providers.base import LLMProvider

#: Claims fed to LLM synthesis (cost bound) and cited by the answer.
_MAX_ANSWER_CLAIMS = 10
#: Claims concatenated by the deterministic fallback.
_MAX_FALLBACK_CLAIMS = 3
#: Gaps named in the remaining-uncertainty statement.
_MAX_NAMED_GAPS = 3


class AnswerGenerator:
    """Synthesizes the final answer from the completed knowledge model."""

    def __init__(self, llm: LLMProvider | None = None, attempts: int = 2) -> None:
        self._llm = llm
        self._attempts = max(1, attempts)

    def generate(
        self,
        *,
        plan: ResearchPlan,
        claims: list[Claim],
        confidence: ConfidenceReport,
        open_gaps: list[KnowledgeGap],
    ) -> Answer:
        """Answer the research objective from the verified knowledge model."""
        supporting = _answer_claims(claims)
        if not supporting:
            return Answer(
                text="",
                reasoning=(
                    "No verified claims support an answer; the evidence gaps "
                    "are stated explicitly in the report."
                ),
                confidence=0.0,
                remaining_uncertainty=_uncertainty(open_gaps, confidence),
            )

        text = self._answer_text(plan, supporting)
        return Answer(
            text=text,
            reasoning=_reasoning(supporting, confidence),
            confidence=confidence.score,
            claim_ids=[c.id for c in supporting],
            remaining_uncertainty=_uncertainty(open_gaps, confidence),
        )

    def executive_summary(
        self,
        plan: ResearchPlan,
        findings: list[Finding],
        answer: Answer,
        confidence: ConfidenceReport,
    ) -> str:
        """A 2-4 sentence summary of what research established."""
        deterministic = _deterministic_summary(plan, findings, answer, confidence)
        if self._llm is None or not self._llm.available:
            return deterministic
        finding_lines = "\n".join(f"- {f.statement}" for f in findings)
        answer_line = f"\nANSWER: {answer.text}" if answer.text else ""
        prompt = (
            f"Write a concise 2-4 sentence executive summary for a research "
            f"report on '{plan.objective}'. Base it only on these findings "
            f"and do not invent facts:\n{finding_lines or '- (none)'}"
            f"{answer_line}\n\n"
            f"Note the overall confidence is {confidence.score:.0%}."
        )
        generated = self._generate(
            prompt, system="You are a precise research synthesis assistant."
        )
        return generated.strip() if generated else deterministic

    # -- synthesis ------------------------------------------------------------

    def _answer_text(self, plan: ResearchPlan, supporting: list[Claim]) -> str:
        deterministic = " ".join(
            c.text for c in supporting[:_MAX_FALLBACK_CLAIMS]
        )
        if self._llm is None or not self._llm.available:
            return deterministic
        claim_lines = "\n".join(f"- {c.text}" for c in supporting)
        target = (
            f"Answer the question below directly"
            if plan.is_question
            else "State the core understanding of the subject below"
        )
        prompt = (
            f"{target}, in 2-4 sentences, using ONLY the verified claims "
            f"provided. Do not add outside facts. If the claims only "
            f"partially cover it, state what can be established and what "
            f"remains open.\n\n"
            f"{'QUESTION' if plan.is_question else 'SUBJECT'}: {plan.question}\n\n"
            f"VERIFIED CLAIMS (most important first):\n{claim_lines}"
        )
        generated = self._generate(
            prompt,
            system="You answer research questions strictly from verified claims.",
        )
        return generated.strip() if generated else deterministic

    def _generate(self, prompt: str, system: str) -> str | None:
        """Call the LLM with a light retry (the model can be nondeterministic)."""
        if self._llm is None:
            return None
        for _ in range(self._attempts):
            text = self._llm.generate(prompt, system=system)
            if text and text.strip():
                return text
        return None


def _answer_claims(claims: list[Claim]) -> list[Claim]:
    """The claims an answer may rest on, most important first.

    Open questions assert nothing and contradicted claims are unresolved;
    neither can support an answer. Importance leads the ranking (principle 5),
    with confidence and corroboration breaking ties.
    """
    usable = [
        c
        for c in claims
        if c.claim_type is not ClaimType.OPEN_QUESTION
        and c.status is not VerificationStatus.CONTRADICTED
    ]
    usable.sort(
        key=lambda c: (c.importance, c.confidence, c.supporting_sources, c.id),
        reverse=True,
    )
    return usable[:_MAX_ANSWER_CLAIMS]


def _reasoning(supporting: list[Claim], confidence: ConfidenceReport) -> str:
    corroborated = sum(
        1 for c in supporting if c.status is VerificationStatus.CORROBORATED
    )
    return (
        f"Synthesized from the {len(supporting)} most important verified "
        f"claims ({corroborated} independently corroborated); "
        f"{confidence.explanation}"
    )


def _uncertainty(
    open_gaps: list[KnowledgeGap], confidence: ConfidenceReport
) -> str:
    if not open_gaps:
        return (
            f"No open knowledge gaps remain; confidence is bounded at "
            f"{confidence.score:.0%} by source diversity and coverage."
        )
    named = "; ".join(g.description for g in open_gaps[:_MAX_NAMED_GAPS])
    extra = len(open_gaps) - _MAX_NAMED_GAPS
    suffix = f" (+{extra} further gap(s))" if extra > 0 else ""
    return f"Unresolved: {named}{suffix}"


def _deterministic_summary(
    plan: ResearchPlan,
    findings: list[Finding],
    answer: Answer,
    confidence: ConfidenceReport,
) -> str:
    if not findings:
        return (
            f"This report investigated '{plan.question}', but no verified "
            f"evidence was collected. The evidence gaps are listed explicitly; "
            f"see missing evidence and open questions for next steps."
        )
    lead = answer.text or findings[0].statement
    return (
        f"This report investigated '{plan.question}' across "
        f"{len(plan.subquestions)} subquestions, producing "
        f"{len(findings)} evidence-backed findings at an overall "
        f"confidence of {confidence.score:.0%}. {lead} "
        f"Confidence is bounded by source diversity and coverage; see the "
        f"uncertainty section for the factor breakdown."
    )
