"""Reasoning engine.

Operates exclusively on **verified claims**, the evidence graph, and the
research objective — never on raw documents or webpages (``OBJECTIVE.md``
module 9). It identifies patterns, weighs contradictions, finds missing
evidence (which drives the research loop), generates hypotheses, produces
conclusions — including a direct answer when the input was a question — and
estimates uncertainty through the deterministic confidence model.

An optional LLM is used only for semantic synthesis (phrasing findings, the
direct answer, hypotheses, the executive summary) and is always grounded in
the verified claims it is given; a deterministic fallback exists for every
step, so the engine reasons end-to-end offline.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from research_engine.domain.models import (
    Claim,
    ClaimType,
    ConfidenceReport,
    Contradiction,
    Evidence,
    Finding,
    Hypothesis,
    ResearchPlan,
    Source,
    SubQuestion,
    VerificationStatus,
)
from research_engine.knowledge.graph import EvidenceGraph
from research_engine.logging_setup import get_logger
from research_engine.providers.base import LLMProvider
from research_engine.reasoning.confidence import (
    ConfidenceInputs,
    ConfidenceModel,
    claim_specificity,
)
from research_engine.utils import parse_json_array

_log = get_logger("reasoning.analyzer")

#: Claims fed to LLM synthesis per call (cost bound).
_MAX_CLAIMS_PER_PROMPT = 8


@dataclass
class ReasoningResult:
    """Everything the reasoning engine derives from the verified claims."""

    findings: list[Finding] = field(default_factory=list)
    #: Direct answer to the research question ("" when not answerable).
    direct_answer: str = ""
    #: Cross-cutting patterns observed across subquestions.
    patterns: list[str] = field(default_factory=list)
    hypotheses: list[Hypothesis] = field(default_factory=list)
    #: Human-readable evidence gaps.
    missing_evidence: list[str] = field(default_factory=list)
    #: Subquestions with absent/uncorroborated evidence (research-loop targets).
    weak_subquestion_ids: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    confidence: ConfidenceReport = field(default_factory=ConfidenceReport)
    executive_summary: str = ""


class ReasoningEngine:
    """Derives conclusions from verified claims and the evidence graph."""

    def __init__(self, llm: LLMProvider | None = None, attempts: int = 2) -> None:
        self._llm = llm
        self._attempts = max(1, attempts)
        self._confidence = ConfidenceModel()

    def analyze(
        self,
        *,
        plan: ResearchPlan,
        claims: list[Claim],
        graph: EvidenceGraph,
        contradictions: list[Contradiction],
        sources: dict[str, Source],
        evidence: list[Evidence],
    ) -> ReasoningResult:
        result = ReasoningResult()
        evidence_by_id = {e.id: e for e in evidence}

        # 1. Stamp deterministic, explained confidence onto every claim.
        for claim in claims:
            inputs = self._claim_inputs(claim, sources, evidence_by_id)
            claim.confidence = self._confidence.score(inputs)
            claim.confidence_explanation = self._confidence.explain(
                inputs, claim.confidence
            )

        # 2. Findings per subquestion; gaps feed the research loop.
        assertive = [c for c in claims if c.claim_type is not ClaimType.OPEN_QUESTION]
        by_subquestion = _group_by_subquestion(assertive)
        for subquestion in plan.subquestions:
            supporting = by_subquestion.get(subquestion.id, [])
            if not supporting:
                result.missing_evidence.append(
                    f"No verified evidence was collected for: {subquestion.question}"
                )
                result.weak_subquestion_ids.append(subquestion.id)
                continue
            if all(c.supporting_sources < 2 for c in supporting):
                result.missing_evidence.append(
                    "Only single-source (uncorroborated) evidence exists for: "
                    f"{subquestion.question}"
                )
                result.weak_subquestion_ids.append(subquestion.id)
            result.findings.append(
                self._build_finding(subquestion, supporting, sources, evidence_by_id)
            )

        # 3. Patterns, hypotheses, open questions, suggestions.
        result.patterns = _patterns(graph, plan)
        result.hypotheses = self._build_hypotheses(plan, result.findings, graph)
        result.open_questions = _open_questions(claims, contradictions)
        result.suggestions = _suggestions(claims, contradictions, graph)

        # 4. Overall confidence over the whole body of verified claims.
        overall_inputs = self._overall_inputs(
            plan, claims, contradictions, sources, evidence
        )
        result.confidence = self._confidence.report(overall_inputs)

        # 5. Conclusions: direct answer (for questions) + executive summary.
        if plan.is_question:
            result.direct_answer = self._direct_answer(plan, claims)
        result.executive_summary = self._executive_summary(plan, result)
        return result

    # -- confidence inputs --------------------------------------------------

    def _claim_inputs(
        self,
        claim: Claim,
        sources: dict[str, Source],
        evidence_by_id: dict[str, Evidence],
    ) -> ConfidenceInputs:
        authorities = [
            sources[sid].authority for sid in claim.source_ids if sid in sources
        ]
        relevances = [
            evidence_by_id[eid].relevance_score
            for eid in claim.evidence_ids
            if eid in evidence_by_id
        ]
        return ConfidenceInputs(
            supporting_sources=claim.supporting_sources,
            independent_domains=claim.independent_domains,
            mean_authority=_mean(authorities),
            agreement=claim.agreement,
            contradictions=len(claim.contradicts),
            coverage=None,  # coverage is a plan-level notion
            evidence_quality=_mean(relevances),
            specificity=claim_specificity(claim.claim_type),
        )

    def _aggregate_inputs(
        self,
        claims: list[Claim],
        sources: dict[str, Source],
        evidence_by_id: dict[str, Evidence],
        *,
        coverage: float | None,
        contradiction_count: int,
    ) -> ConfidenceInputs:
        source_ids = {sid for c in claims for sid in c.source_ids}
        contributing = [sources[sid] for sid in source_ids if sid in sources]
        domains = {s.domain for s in contributing if s.domain}
        relevances = [
            evidence_by_id[eid].relevance_score
            for c in claims
            for eid in c.evidence_ids
            if eid in evidence_by_id
        ]
        return ConfidenceInputs(
            supporting_sources=len(source_ids),
            independent_domains=len(domains),
            mean_authority=_mean([s.authority for s in contributing]),
            agreement=_mean([c.agreement for c in claims]),
            contradictions=contradiction_count,
            coverage=coverage,
            evidence_quality=_mean(relevances),
            specificity=_mean([claim_specificity(c.claim_type) for c in claims]),
        )

    def _overall_inputs(
        self,
        plan: ResearchPlan,
        claims: list[Claim],
        contradictions: list[Contradiction],
        sources: dict[str, Source],
        evidence: list[Evidence],
    ) -> ConfidenceInputs:
        evidence_by_id = {e.id: e for e in evidence}
        answered = {
            sq.id
            for sq in plan.subquestions
            if any(sq.id in c.subquestion_ids for c in claims)
        }
        coverage = len(answered) / len(plan.subquestions) if plan.subquestions else 0.0
        return self._aggregate_inputs(
            claims,
            sources,
            evidence_by_id,
            coverage=coverage,
            contradiction_count=len(contradictions),
        )

    # -- findings -------------------------------------------------------------

    def _build_finding(
        self,
        subquestion: SubQuestion,
        supporting: list[Claim],
        sources: dict[str, Source],
        evidence_by_id: dict[str, Evidence],
    ) -> Finding:
        # Prefer claims whose *primary* subquestion is this one, so findings
        # stay distinct even when merged claims span several subquestions.
        ranked = sorted(
            supporting,
            key=lambda c: (
                bool(c.subquestion_ids and c.subquestion_ids[0] == subquestion.id),
                c.confidence,
                c.supporting_sources,
                c.id,
            ),
            reverse=True,
        )
        top = ranked[:_MAX_CLAIMS_PER_PROMPT]
        inputs = self._aggregate_inputs(
            supporting,
            sources,
            evidence_by_id,
            coverage=None,
            contradiction_count=sum(1 for c in supporting if c.contradicts),
        )
        confidence = self._confidence.score(inputs)
        statement = self._finding_statement(subquestion, top)
        return Finding(
            id=f"find-{subquestion.id}",
            statement=statement,
            claim_ids=[c.id for c in ranked],
            subquestion_id=subquestion.id,
            confidence=confidence,
            confidence_explanation=self._confidence.explain(inputs, confidence),
        )

    def _finding_statement(
        self, subquestion: SubQuestion, top_claims: list[Claim]
    ) -> str:
        """Synthesize one finding from a subquestion's strongest claims.

        With an LLM available, the statement is synthesized from the verified
        claims (grounded, no outside facts). Otherwise the strongest claim
        stands as the finding. Both paths cite the same claims.
        """
        deterministic = top_claims[0].text
        if self._llm is None or not self._llm.available:
            return deterministic
        claim_lines = "\n".join(f"- {c.text}" for c in top_claims)
        prompt = (
            f"Answer the research subquestion below in 1-2 declarative sentences, "
            f"using ONLY the verified claims provided. Do not add outside facts. "
            f"If the claims cannot answer it, state what they do establish.\n\n"
            f"SUBQUESTION: {subquestion.question}\n\n"
            f"VERIFIED CLAIMS:\n{claim_lines}"
        )
        generated = self._generate(
            prompt, system="You synthesize grounded research findings from verified claims."
        )
        return generated.strip() if generated else deterministic

    # -- direct answer ---------------------------------------------------------

    def _direct_answer(self, plan: ResearchPlan, claims: list[Claim]) -> str:
        """Answer the research question from the strongest verified claims."""
        usable = sorted(
            (
                c for c in claims
                if c.claim_type is not ClaimType.OPEN_QUESTION
                and c.status is not VerificationStatus.CONTRADICTED
            ),
            key=lambda c: (c.confidence, c.supporting_sources, c.id),
            reverse=True,
        )
        if not usable:
            return ""
        top = usable[:_MAX_CLAIMS_PER_PROMPT]
        deterministic = " ".join(c.text for c in top[:3])
        if self._llm is None or not self._llm.available:
            return deterministic
        claim_lines = "\n".join(f"- {c.text}" for c in top)
        prompt = (
            f"Answer the question below directly, in 2-4 sentences, using ONLY "
            f"the verified claims provided. Do not add outside facts. If the "
            f"claims only partially answer it, answer what can be answered and "
            f"say what remains open.\n\n"
            f"QUESTION: {plan.question}\n\n"
            f"VERIFIED CLAIMS:\n{claim_lines}"
        )
        generated = self._generate(
            prompt, system="You answer research questions strictly from verified claims."
        )
        return generated.strip() if generated else deterministic

    # -- hypotheses --------------------------------------------------------------

    def _build_hypotheses(
        self, plan: ResearchPlan, findings: list[Finding], graph: EvidenceGraph
    ) -> list[Hypothesis]:
        deterministic = _deterministic_hypotheses(graph)
        if self._llm is None or not self._llm.available:
            return deterministic
        generated = self._llm_hypotheses(plan, findings, graph)
        return generated if generated else deterministic

    def _llm_hypotheses(
        self, plan: ResearchPlan, findings: list[Finding], graph: EvidenceGraph
    ) -> list[Hypothesis]:
        """Ask the LLM for grounded, testable hypotheses; ``[]`` if unusable."""
        finding_lines = "\n".join(f"- {f.statement}" for f in findings)
        entity_lines = ", ".join(e.name for e in graph.central_entities(8))
        prompt = (
            f"Based only on the findings and central entities below for research "
            f"on '{plan.objective}', propose up to 5 specific, testable hypotheses "
            f"that plausibly follow from this evidence and are worth further "
            f"investigation. Do not introduce outside facts.\n\n"
            f"FINDINGS:\n{finding_lines or '- (none)'}\n\n"
            f"CENTRAL ENTITIES: {entity_lines or '(none)'}\n\n"
            f"Return ONLY a JSON array of strings, each a single hypothesis."
        )
        raw = self._generate(
            prompt, system="You propose grounded, testable research hypotheses."
        )
        statements = [
            str(s).strip() for s in (parse_json_array(raw) or []) if str(s).strip()
        ]
        if not statements:
            return []
        # Ground each hypothesis in the claims behind the strongest findings.
        claim_ids = sorted({cid for f in findings for cid in f.claim_ids[:3]})
        return [
            Hypothesis(
                id=f"hyp-{index}",
                statement=text,
                claim_ids=claim_ids,
                confidence=0.4,
            )
            for index, text in enumerate(statements[:5], start=1)
        ]

    # -- executive summary --------------------------------------------------------

    def _executive_summary(self, plan: ResearchPlan, result: ReasoningResult) -> str:
        deterministic = _deterministic_summary(plan, result)
        if self._llm is None or not self._llm.available:
            return deterministic
        finding_lines = "\n".join(f"- {f.statement}" for f in result.findings)
        answer_line = (
            f"\nDIRECT ANSWER: {result.direct_answer}" if result.direct_answer else ""
        )
        prompt = (
            f"Write a concise 2-4 sentence executive summary for a research "
            f"report on '{plan.objective}'. Base it only on these findings and "
            f"do not invent facts:\n{finding_lines or '- (none)'}{answer_line}\n\n"
            f"Note the overall confidence is {result.confidence.score:.0%}."
        )
        generated = self._generate(
            prompt, system="You are a precise research synthesis assistant."
        )
        return generated or deterministic

    def _generate(self, prompt: str, system: str) -> str | None:
        """Call the LLM with a light retry (the model can be nondeterministic)."""
        if self._llm is None:
            return None
        for _ in range(self._attempts):
            text = self._llm.generate(prompt, system=system)
            if text and text.strip():
                return text
        return None


# -- deterministic derivations -------------------------------------------------


def _patterns(graph: EvidenceGraph, plan: ResearchPlan) -> list[str]:
    """Entities whose evidence spans multiple subquestions (research focal points)."""
    patterns: list[str] = []
    questions_by_id = {sq.id: sq.question for sq in plan.subquestions}
    for entity in graph.central_entities(10):
        claims = graph.claims_for_entity(entity.name)
        spanned = {sid for c in claims for sid in c.subquestion_ids}
        spanned &= set(questions_by_id)
        if len(spanned) >= 2:
            patterns.append(
                f"'{entity.name}' recurs across {len(spanned)} subquestions "
                f"({len(entity.claim_ids)} claims reference it), suggesting it is "
                f"central to the research objective."
            )
        if len(patterns) >= 5:
            break
    return patterns


def _deterministic_hypotheses(graph: EvidenceGraph) -> list[Hypothesis]:
    """Entity pairs that co-occur in claims suggest relationships to test."""
    pair_claims: dict[tuple[str, str], list[str]] = {}
    for claim in graph.claims:
        names = sorted(set(claim.entities))[:4]
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                pair_claims.setdefault((names[i], names[j]), []).append(claim.id)
    ranked = sorted(
        pair_claims.items(), key=lambda kv: (len(kv[1]), kv[0]), reverse=True
    )
    hypotheses: list[Hypothesis] = []
    for index, ((a, b), claim_ids) in enumerate(ranked[:5], start=1):
        hypotheses.append(
            Hypothesis(
                id=f"hyp-{index}",
                statement=(
                    f"There may be a meaningful relationship between {a} and {b} "
                    f"worth deeper investigation."
                ),
                claim_ids=claim_ids,
                confidence=min(0.5, len(claim_ids) / 4.0),
            )
        )
    return hypotheses


def _open_questions(
    claims: list[Claim], contradictions: list[Contradiction]
) -> list[str]:
    questions: list[str] = []
    for claim in claims:
        if claim.claim_type is ClaimType.OPEN_QUESTION:
            questions.append(claim.text)
    for contradiction in contradictions:
        questions.append(f"How can this conflict be resolved? {contradiction.description}")
    return questions[:8]


def _suggestions(
    claims: list[Claim],
    contradictions: list[Contradiction],
    graph: EvidenceGraph,
) -> list[str]:
    suggestions: list[str] = []
    single = sum(
        1 for c in claims if c.status is VerificationStatus.SINGLE_SOURCE
    )
    if single:
        suggestions.append(
            f"Corroborate the {single} single-source claim(s) with additional "
            f"independent sources."
        )
    if contradictions:
        suggestions.append(
            "Resolve the flagged contradictions by consulting primary sources."
        )
    central = graph.central_entities(1)
    if central:
        suggestions.append(
            f"Investigate the central entity '{central[0].name}' in greater depth."
        )
    suggestions.append(
        "Cross-check the highest-impact claims against primary, externally "
        "verifiable sources."
    )
    return suggestions


def _deterministic_summary(plan: ResearchPlan, result: ReasoningResult) -> str:
    if not result.findings:
        return (
            f"This report investigated '{plan.question}', but no verified "
            f"evidence was collected. The evidence gaps are listed explicitly; "
            f"see missing evidence and open questions for next steps."
        )
    lead = result.direct_answer or result.findings[0].statement
    return (
        f"This report investigated '{plan.question}' across "
        f"{len(plan.subquestions)} subquestions, producing "
        f"{len(result.findings)} evidence-backed findings at an overall "
        f"confidence of {result.confidence.score:.0%}. {lead} "
        f"Confidence is bounded by source diversity and coverage; see the "
        f"uncertainty section for the factor breakdown."
    )


def _group_by_subquestion(claims: list[Claim]) -> dict[str, list[Claim]]:
    grouped: dict[str, list[Claim]] = {}
    for claim in claims:
        for subquestion_id in claim.subquestion_ids:
            grouped.setdefault(subquestion_id, []).append(claim)
    return grouped


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0
