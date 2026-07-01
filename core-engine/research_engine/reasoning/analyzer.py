"""Reasoning & analysis.

Operates on structured evidence (never raw documents) to produce findings,
hypotheses, confidence estimates, knowledge gaps, and an executive summary.
Reasoning is explainable: every finding and hypothesis links back to the
evidence that supports it. An optional LLM enriches the executive-summary
narrative; a deterministic fallback is always available.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from research_engine.domain.models import (
    Contradiction,
    Entity,
    Evidence,
    Finding,
    Hypothesis,
    Task,
    TaskKind,
)
from research_engine.knowledge.graph import KnowledgeGraph
from research_engine.providers.base import LLMProvider


@dataclass
class ReasoningResult:
    """Bundle of everything the reasoning subsystem derives."""

    findings: list[Finding] = field(default_factory=list)
    hypotheses: list[Hypothesis] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    overall_confidence: float = 0.0
    executive_summary: str = ""


class ReasoningEngine:
    """Derives insights from evidence and the knowledge graph."""

    def __init__(self, llm: LLMProvider | None = None, attempts: int = 2) -> None:
        self._llm = llm
        self._attempts = max(1, attempts)

    def _generate(self, prompt: str, system: str) -> str | None:
        """Call the LLM with a light retry (the model can be nondeterministic)."""
        if self._llm is None:
            return None
        for _ in range(self._attempts):
            text = self._llm.generate(prompt, system=system)
            if text and text.strip():
                return text
        return None

    def analyze(
        self,
        *,
        topic: str,
        tasks: list[Task],
        evidence: list[Evidence],
        knowledge_graph: KnowledgeGraph,
        contradictions: list[Contradiction],
        documents_per_query: int,
    ) -> ReasoningResult:
        result = ReasoningResult()
        by_task = _group_by_task(evidence)

        result.findings = self._build_findings(tasks, by_task, documents_per_query)
        result.hypotheses = self._build_hypotheses(
            topic, result.findings, knowledge_graph
        )
        result.overall_confidence = _mean(
            [f.confidence for f in result.findings]
        )
        result.open_questions = self._open_questions(
            tasks, by_task, contradictions
        )
        result.suggestions = self._suggestions(knowledge_graph)
        result.executive_summary = self._executive_summary(
            topic, result.findings, result.overall_confidence
        )
        return result

    # -- findings ---------------------------------------------------------

    def _build_findings(
        self,
        tasks: list[Task],
        by_task: dict[str, list[Evidence]],
        documents_per_query: int,
    ) -> list[Finding]:
        findings: list[Finding] = []
        index = 0
        for task in tasks:
            if task.kind is not TaskKind.COLLECT:
                continue
            items = by_task.get(task.id, [])
            if not items:
                continue
            index += 1
            distinct_sources = len({e.source_id for e in items})
            # Scale by (documents_per_query + 1) so confidence stays below
            # certainty: there is always room for one more corroborating source.
            confidence = min(1.0, distinct_sources / (documents_per_query + 1))
            angle = _angle(task)
            findings.append(
                Finding(
                    id=f"find-{index}",
                    statement=self._finding_statement(angle, items),
                    supporting_evidence_ids=[e.id for e in items],
                    confidence=confidence,
                )
            )
        return findings

    def _finding_statement(self, angle: str, items: list[Evidence]) -> str:
        """Synthesize a finding for one angle from its supporting evidence.

        With an LLM available, the statement is synthesized from the angle's
        claims (grounded, no outside facts). Otherwise a representative claim is
        used. Both paths cite the same supporting evidence.
        """
        representative = max(items, key=lambda e: len(e.entities))
        deterministic = f"On {angle}: {representative.claim}"
        if self._llm is None or not self._llm.available:
            return deterministic

        # Send the most entity-rich claims (bounded, for cost) as grounding.
        top = sorted(items, key=lambda e: len(e.entities), reverse=True)[:8]
        claim_lines = "\n".join(f"- {e.claim}" for e in top)
        prompt = (
            f"Synthesize a single, specific finding (1-2 sentences) about "
            f"'{angle}'. Base it strictly on the evidence below and do not add "
            f"outside facts. Write it as a declarative statement, not a list.\n\n"
            f"EVIDENCE:\n{claim_lines}"
        )
        generated = self._generate(
            prompt, system="You synthesize grounded research findings from evidence."
        )
        if not generated:
            return deterministic
        return f"On {angle}: {generated.strip()}"

    # -- hypotheses -------------------------------------------------------

    def _build_hypotheses(
        self, topic: str, findings: list[Finding], graph: KnowledgeGraph
    ) -> list[Hypothesis]:
        deterministic = self._deterministic_hypotheses(graph)
        if self._llm is None or not self._llm.available:
            return deterministic
        generated = self._llm_hypotheses(topic, findings, graph)
        return generated if generated else deterministic

    def _llm_hypotheses(
        self, topic: str, findings: list[Finding], graph: KnowledgeGraph
    ) -> list[Hypothesis]:
        """Ask the LLM for grounded, testable hypotheses; ``[]`` if unusable."""
        top_rels = sorted(
            graph.relationships,
            key=lambda r: (len(r.evidence_ids), r.id),
            reverse=True,
        )[:8]
        names = {e.id: e.name for e in graph.entities}
        rel_lines = "\n".join(
            f"- {names.get(r.source_entity_id, r.source_entity_id)} "
            f"{r.relation} {names.get(r.target_entity_id, r.target_entity_id)}"
            for r in top_rels
        )
        finding_lines = "\n".join(f"- {f.statement}" for f in findings)
        prompt = (
            f"Based only on the findings and entity relationships below for "
            f"research on '{topic}', propose up to 5 specific, testable hypotheses "
            f"that plausibly follow from this evidence and are worth further "
            f"investigation. Do not introduce outside facts.\n\n"
            f"FINDINGS:\n{finding_lines or '- (none)'}\n\n"
            f"RELATIONSHIPS:\n{rel_lines or '- (none)'}\n\n"
            f'Return ONLY a JSON array of strings, each a single hypothesis.'
        )
        raw = self._generate(
            prompt, system="You propose grounded, testable research hypotheses."
        )
        statements = _parse_string_array(raw)
        if not statements:
            return []
        # Ground each hypothesis in the evidence behind the strongest relationships.
        evidence_ids = sorted({e for r in top_rels for e in r.evidence_ids})
        return [
            Hypothesis(
                id=f"hyp-{index}",
                statement=text,
                supporting_evidence_ids=list(evidence_ids),
                confidence=0.4,
            )
            for index, text in enumerate(statements[:5], start=1)
        ]

    def _deterministic_hypotheses(self, graph: KnowledgeGraph) -> list[Hypothesis]:
        relationships = sorted(
            graph.relationships,
            key=lambda r: (len(r.evidence_ids), r.id),
            reverse=True,
        )[:5]
        names = {e.id: e.name for e in graph.entities}
        hypotheses: list[Hypothesis] = []
        for index, rel in enumerate(relationships, start=1):
            a = names.get(rel.source_entity_id, rel.source_entity_id)
            b = names.get(rel.target_entity_id, rel.target_entity_id)
            confidence = min(0.5, len(rel.evidence_ids) / 4.0)
            hypotheses.append(
                Hypothesis(
                    id=f"hyp-{index}",
                    statement=(
                        f"There may be a meaningful relationship between "
                        f"{a} and {b} worth deeper investigation."
                    ),
                    supporting_evidence_ids=list(rel.evidence_ids),
                    confidence=confidence,
                )
            )
        return hypotheses

    # -- gaps & suggestions ----------------------------------------------

    def _open_questions(
        self,
        tasks: list[Task],
        by_task: dict[str, list[Evidence]],
        contradictions: list[Contradiction],
    ) -> list[str]:
        questions: list[str] = []
        for task in tasks:
            if task.kind is not TaskKind.COLLECT:
                continue
            items = by_task.get(task.id, [])
            distinct_sources = len({e.source_id for e in items})
            if distinct_sources < 2:
                questions.append(
                    f"What additional independent sources corroborate {_angle(task)}?"
                )
        if contradictions:
            questions.append(
                "How can the conflicting claims flagged during processing be resolved?"
            )
        questions.append(
            "Which primary, externally-verifiable sources most strongly support "
            "these findings?"
        )
        return questions

    def _suggestions(self, graph: KnowledgeGraph) -> list[str]:
        suggestions = [
            "Corroborate the lowest-confidence angles with additional "
            "independent sources.",
            "Cross-check claims against primary sources where the evidence is "
            "currently single-sourced.",
        ]
        top = _top_entity(graph.entities)
        if top is not None:
            suggestions.append(
                f"Investigate the central entity '{top.name}' in greater depth."
            )
        return suggestions

    # -- executive summary -----------------------------------------------

    def _executive_summary(
        self, topic: str, findings: list[Finding], overall_confidence: float
    ) -> str:
        deterministic = self._deterministic_summary(topic, findings, overall_confidence)
        if self._llm is None or not self._llm.available:
            return deterministic

        bullet_lines = "\n".join(f"- {f.statement}" for f in findings)
        prompt = (
            f"Write a concise 2-4 sentence executive summary for a research report "
            f"on '{topic}'. Base it only on these findings and do not invent facts:\n"
            f"{bullet_lines}\n\n"
            f"Note the overall confidence is {overall_confidence:.0%}."
        )
        generated = self._generate(
            prompt, system="You are a precise research synthesis assistant."
        )
        return generated or deterministic

    @staticmethod
    def _deterministic_summary(
        topic: str, findings: list[Finding], overall_confidence: float
    ) -> str:
        if not findings:
            return (
                f"This report investigated '{topic}', but no evidence was "
                f"successfully collected. See open questions for next steps."
            )
        lead = findings[0].statement
        return (
            f"This report investigated '{topic}' across {len(findings)} research "
            f"angles, producing findings at an overall confidence of "
            f"{overall_confidence:.0%}. A representative finding: {lead} "
            f"Confidence is bounded by source diversity; see the confidence "
            f"assessment and open questions for caveats."
        )


def _group_by_task(evidence: list[Evidence]) -> dict[str, list[Evidence]]:
    grouped: dict[str, list[Evidence]] = {}
    for item in evidence:
        grouped.setdefault(item.task_id, []).append(item)
    return grouped


def _angle(task: Task) -> str:
    text = task.query or task.description
    return text[0].lower() + text[1:] if text else text


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _top_entity(entities: list[Entity]) -> Entity | None:
    if not entities:
        return None
    return max(entities, key=lambda e: (len(e.evidence_ids), e.name))


def _parse_string_array(raw: str | None) -> list[str]:
    """Parse an LLM response into a list of non-empty strings (best-effort)."""
    if not raw:
        return []
    start = raw.find("[")
    end = raw.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [str(item).strip() for item in data if str(item).strip()]
