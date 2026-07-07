"""Reasoning engine.

Operates exclusively on **verified claims**, the knowledge model, and the
research objective — never on raw documents or webpages. It runs inside every
research-loop iteration (reasoning drives research, ``OBJECTIVE.md`` principle
3): it stamps explained confidence on every claim, builds findings per
subquestion, identifies patterns, weighs contradictions, flags weak
subquestions (which feed the curiosity engine), generates hypotheses, and
estimates uncertainty through the deterministic confidence model.

Answer generation and the executive summary live in ``reasoning/answer.py``:
they consume the *completed* knowledge model once the loop has stopped.

An optional LLM is used only for semantic synthesis (phrasing findings,
hypotheses) and is always grounded in the verified claims it is given; a
deterministic fallback exists for every step, so the engine reasons
end-to-end offline.
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
from research_engine.concurrency import parallel_map
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


class ReasoningEngine:
    """Derives conclusions from verified claims and the evidence graph."""

    def __init__(
        self,
        llm: LLMProvider | None = None,
        attempts: int = 2,
        max_workers: int = 1,
    ) -> None:
        self._llm = llm
        self._attempts = max(1, attempts)
        self._max_workers = max(1, max_workers)
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
        #    Classification (missing/weak) is deterministic and sequential;
        #    the finding *statements* each carry an independent LLM call, so
        #    they fan out across the pool. ``parallel_map`` preserves plan
        #    order, so the findings list is identical to the sequential path.
        assertive = [c for c in claims if c.claim_type is not ClaimType.OPEN_QUESTION]
        by_subquestion = _group_by_subquestion(assertive)
        to_build: list[tuple[SubQuestion, list[Claim]]] = []
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
            to_build.append((subquestion, supporting))
        result.findings = parallel_map(
            lambda item: self._build_finding(
                item[0], item[1], sources, evidence_by_id
            ),
            to_build,
            self._max_workers,
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
        return result

    def assess_confidence(
        self,
        *,
        plan: ResearchPlan,
        claims: list[Claim],
        contradictions: list[Contradiction],
        sources: dict[str, Source],
        evidence: list[Evidence],
    ) -> ConfidenceReport:
        """Deterministic overall confidence for the current knowledge model.

        The cheap, LLM-free subset of :meth:`analyze` the research loop needs
        every iteration for its stopping decision. The expensive narrative
        (LLM-phrased findings and hypotheses) is generated once, at the end, via
        :meth:`analyze` — regenerating it on every iteration only to discard all
        but the last was the loop's dominant, unparallelised cost.
        """
        return self._confidence.report(
            self._overall_inputs(plan, claims, contradictions, sources, evidence)
        )

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
        # stay distinct even when merged claims span several subquestions;
        # importance leads within that (principle 5: high-impact knowledge
        # drives conclusions).
        ranked = sorted(
            supporting,
            key=lambda c: (
                bool(c.subquestion_ids and c.subquestion_ids[0] == subquestion.id),
                c.importance,
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


def _group_by_subquestion(claims: list[Claim]) -> dict[str, list[Claim]]:
    grouped: dict[str, list[Claim]] = {}
    for claim in claims:
        for subquestion_id in claim.subquestion_ids:
            grouped.setdefault(subquestion_id, []).append(claim)
    return grouped


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0
