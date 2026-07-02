"""Shared domain models.

These dataclasses are the *only* contract between subsystems. No subsystem
imports another subsystem's implementation; they exchange these types. Keeping
the models in one module makes the data flow explicit and the boundaries stable.

The knowledge-first agent loop of a session (v0.5), expressed in these types::

    ResearchRequest
        -> ResearchPlan + Task[]        (planner)
        -> SearchTask[]                 (adaptive planning, every iteration)
        -> SearchCandidate[]            (retrieval, metadata only)
        -> SearchCandidate[] (accepted) (candidate evaluation)
        -> RawDocument[]                (download; stamped with gain scores)
        -> Evidence[]                   (passage extraction)
        -> Claim[]                      (claim extraction + normalization)
        -> Claim[] (verified, importance-ranked)   (verification + reasoning)
        -> GraphNode[]/GraphEdge[]      (knowledge model)
        -> KnowledgeGap[]               (curiosity — drives the next iteration)
        -> IterationRecord[]            (information gain per iteration)
        -> Finding[] + Hypothesis[] + Contradiction[] + ConfidenceReport
                                        (reasoning over the knowledge model)
        -> Answer                       (answer generation from knowledge)
        -> ResearchReport               (rendering of the knowledge model)

Documents are evidence containers; the primary reasoning unit is the verified
claim; the knowledge model (claims + graph) is the product of research and the
report is a rendering of it. The provenance chain is explicit and always
preserved: answer/finding -> claim -> evidence -> document -> source.

``KnowledgeGap`` and ``SearchTask`` live here deliberately: the curiosity
engine (reasoning layer) *produces* gaps and the planner *consumes* them, so
routing them through the shared domain keeps module dependencies one-way.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TaskStatus(str, Enum):
    """Lifecycle state of a research task."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskKind(str, Enum):
    """The role a task plays in the research plan."""

    COLLECT = "collect"
    SYNTHESIZE = "synthesize"


class ClaimType(str, Enum):
    """What kind of assertion a claim makes (``OBJECTIVE.md`` module 5)."""

    FACT = "fact"
    DEFINITION = "definition"
    NUMERICAL = "numerical"
    DATE = "date"
    LIMITATION = "limitation"
    ASSUMPTION = "assumption"
    METHOD = "method"
    OPEN_QUESTION = "open_question"


class VerificationStatus(str, Enum):
    """Outcome of cross-source claim verification."""

    #: Verification has not run for this claim (e.g. verification disabled).
    UNVERIFIED = "unverified"
    #: Asserted by two or more independent sources, no conflicts.
    CORROBORATED = "corroborated"
    #: Asserted by a single source only (unsupported by independent evidence).
    SINGLE_SOURCE = "single_source"
    #: At least one other claim conflicts with this one.
    CONTRADICTED = "contradicted"


class GapKind(str, Enum):
    """What kind of missing knowledge a :class:`KnowledgeGap` describes."""

    #: A subquestion with no verified evidence at all.
    MISSING_EVIDENCE = "missing_evidence"
    #: A subquestion whose evidence is single-source only.
    UNCORROBORATED = "uncorroborated"
    #: A central entity that no definition claim covers.
    MISSING_DEFINITION = "missing_definition"
    #: A central entity with no relationship to the rest of the knowledge model.
    MISSING_RELATIONSHIP = "missing_relationship"
    #: Conflicting claims that need investigation to resolve.
    CONTRADICTION = "contradiction"
    #: Important claims supported only by low-authority sources.
    MISSING_PRIMARY_SOURCE = "missing_primary_source"


def confidence_label(score: float) -> str:
    """Map a 0..1 confidence score to a coarse human label."""
    if score >= 0.66:
        return "high"
    if score >= 0.33:
        return "medium"
    return "low"


@dataclass
class ResearchRequest:
    """A user's request to research a question or topic.

    ``topic`` is the raw user input — either a broad topic ("quantum
    computing") or a direct question ("what limits quantum error correction?").
    The planner understands the difference; the field name is kept for CLI/API
    interface stability.
    """

    topic: str
    max_subtopics: int = 6
    documents_per_query: int = 3


@dataclass
class SubQuestion:
    """One focused question the plan decomposes the research objective into."""

    id: str
    question: str
    #: Search-engine queries generated to answer this subquestion.
    search_queries: list[str] = field(default_factory=list)


@dataclass
class ResearchPlan:
    """Structured output of the research planner (``OBJECTIVE.md`` module 1).

    Produced *before* any searching so retrieval is targeted. ``exclusion_criteria``
    terms are used by candidate evaluation to reject out-of-scope results.
    """

    #: What the research is trying to establish, as one sentence.
    objective: str
    #: The raw user input the plan was derived from.
    question: str
    #: Whether the input was phrased as a question (vs. a broad topic).
    is_question: bool = False
    #: The core subject extracted from the input (used for relevance signals).
    subject: str = ""
    subquestions: list[SubQuestion] = field(default_factory=list)
    #: Entities the planner expects evidence to mention (relevance signal).
    expected_entities: list[str] = field(default_factory=list)
    #: Kinds of evidence expected (e.g. "definitions", "numerical data").
    expected_evidence_types: list[str] = field(default_factory=list)
    #: Kinds of sources expected (e.g. "peer-reviewed", "encyclopedia").
    expected_source_types: list[str] = field(default_factory=list)
    #: One-sentence statement of what is in scope.
    scope: str = ""
    #: Terms/subjects that indicate an irrelevant result (rejection signal).
    exclusion_criteria: list[str] = field(default_factory=list)
    #: Which strategy produced the plan: "llm" or "deterministic".
    planner: str = "deterministic"


@dataclass
class Task:
    """A node in the research task graph."""

    id: str
    description: str
    kind: TaskKind
    query: str = ""
    #: The subquestion this task collects evidence for ("" for synthesis).
    subquestion_id: str = ""
    depends_on: list[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    error: str | None = None


@dataclass
class KnowledgeGap:
    """A specific piece of missing knowledge, discovered by the curiosity engine.

    Gaps are the fuel of the research loop: each open gap can be converted by
    the adaptive planner into a targeted :class:`SearchTask`. Gaps persist in
    the session so the report can state what was investigated and what remains
    unknown.
    """

    id: str
    kind: GapKind
    #: Human-readable statement of what is missing and why it matters.
    description: str
    #: A search query expected to close the gap.
    suggested_query: str = ""
    #: Subquestion the gap belongs to ("" for cross-cutting gaps).
    subquestion_id: str = ""
    #: Entity the gap concerns ("" when not entity-specific).
    entity: str = ""
    #: 0..1 — how much closing this gap would advance the objective.
    priority: float = 0.5
    #: Whether the planner has already turned this gap into a search task.
    investigated: bool = False


@dataclass
class SearchTask:
    """One prioritized retrieval action emitted by the adaptive planner.

    Unlike a bare query string, a search task records *why* it exists — the
    knowledge it is expected to produce — so every retrieval performed by the
    agent is explainable and auditable.
    """

    id: str
    query: str
    #: What knowledge this search is meant to produce.
    objective: str
    #: Why the planner created it (initial plan / which gap it targets).
    reason: str
    #: The kind of information expected (e.g. "definition", "corroboration").
    expected_information: str = ""
    #: 0..1 execution priority within an iteration.
    priority: float = 0.5
    subquestion_id: str = ""
    #: Gap that produced this task ("" for initial-plan tasks).
    gap_id: str = ""
    #: Research-loop iteration the task was created for.
    iteration: int = 1


@dataclass
class IterationRecord:
    """What one research-loop iteration contributed to the knowledge model.

    The information-gain analyzer fills these in; the stopping engine reads
    them to detect when further searching has stopped teaching the engine
    anything new.
    """

    iteration: int
    search_tasks: int = 0
    documents_downloaded: int = 0
    #: Claims that existed before / after this iteration's knowledge update.
    claims_before: int = 0
    claims_after: int = 0
    #: Newly corroborated claims after this iteration.
    corroborated: int = 0
    #: 0..1 fraction of this iteration's claims that were genuinely new.
    novelty: float = 0.0
    #: 0..1 normalized knowledge growth contributed by this iteration.
    knowledge_gain: float = 0.0
    #: Overall confidence after this iteration.
    confidence: float = 0.0
    #: Open knowledge gaps remaining after this iteration.
    gaps_open: int = 0


@dataclass
class Answer:
    """The direct answer synthesized from the completed knowledge model.

    The answer — not the report — is the primary product of a research run
    (``OBJECTIVE.md`` principle 1). ``claim_ids`` cite the verified claims the
    answer rests on, preserving the provenance chain.
    """

    text: str
    #: Why the knowledge model supports this answer.
    reasoning: str = ""
    confidence: float = 0.0
    claim_ids: list[str] = field(default_factory=list)
    #: What remains unknown or uncertain after research.
    remaining_uncertainty: str = ""

    @property
    def confidence_label(self) -> str:
        return confidence_label(self.confidence)


@dataclass
class Source:
    """Provenance for a document.

    ``authority``/``authority_tier``/``domain`` are populated by candidate
    evaluation: a deterministic source-quality assessment that feeds confidence
    estimation. They default to a neutral "unknown" so sources created outside
    that stage remain valid.
    """

    id: str
    title: str
    provider: str
    locator: str = ""  # URL, file path, or other reference
    retrieved_at: str = ""
    #: Network domain parsed from ``locator`` (e.g. "arxiv.org"); "" if none.
    domain: str = ""
    #: 0..1 source-authority score.
    authority: float = 0.0
    #: Human-readable authority tier (e.g. "peer-reviewed", "encyclopedia").
    authority_tier: str = "unknown"


@dataclass
class SearchCandidate:
    """A search result *before* download: metadata only, no page content.

    Candidate evaluation operates exclusively on these fields (title, snippet,
    URL, source metadata); documents are downloaded only for accepted
    candidates. This is what keeps irrelevant pages out of the bandwidth and
    token budget.
    """

    id: str
    query: str
    title: str
    snippet: str
    url: str
    provider: str
    #: Provider-specific fetch key (e.g. a Wikipedia page id); url if none.
    ref: str = ""
    subquestion_id: str = ""
    task_id: str = ""
    #: Stamped by candidate evaluation.
    domain: str = ""
    authority: float = 0.0
    authority_tier: str = "unknown"
    relevance_score: float = 0.0
    accepted: bool = False
    #: Why the candidate was rejected ("" when accepted).
    rejection_reason: str = ""


@dataclass
class RawDocument:
    """A downloaded document. An evidence *container*, never a reasoning unit."""

    id: str
    query: str
    task_id: str
    title: str
    content: str
    source: Source
    subquestion_id: str = ""
    #: 0..1 topical-relevance score inherited from its accepted candidate.
    relevance_score: float = 0.0

    # -- information-gain scores (stamped by the gain analyzer) -------------
    #: 0..1 fraction of the document's claims that were new knowledge.
    novelty_score: float = 0.0
    #: 0..1 how much the document advanced unanswered subquestions.
    coverage_score: float = 0.0
    #: 0..1 fraction of the document's claims that duplicated known claims.
    redundancy_score: float = 0.0
    #: Claims contributed per evidence passage (≥ 0).
    evidence_density: float = 0.0
    #: 0..1 mean importance of the claims the document contributed.
    importance_score: float = 0.0


@dataclass
class Evidence:
    """A relevant passage extracted from a document, with provenance.

    Evidence is the link between claims and documents: every claim references
    the evidence passages it was extracted from, and every evidence item
    references its originating document and source.
    """

    id: str
    passage: str
    document_id: str
    source_id: str
    task_id: str = ""
    subquestion_id: str = ""
    #: 0..1 relevance of this passage to its subquestion.
    relevance_score: float = 0.0


@dataclass
class Claim:
    """The primary reasoning unit: a canonical, typed, verifiable assertion.

    Claims are extracted from evidence passages, normalized (equivalent
    wordings merged), then verified across sources. Verification metadata is
    stamped directly onto the claim so downstream reasoning never needs the
    original documents.
    """

    id: str
    #: The canonical statement of the claim.
    text: str
    claim_type: ClaimType = ClaimType.FACT
    entities: list[str] = field(default_factory=list)
    #: Provenance: evidence passages this claim was extracted from.
    evidence_ids: list[str] = field(default_factory=list)
    #: Distinct sources asserting the claim (derived from evidence).
    source_ids: list[str] = field(default_factory=list)
    #: Subquestions this claim is evidence for.
    subquestion_ids: list[str] = field(default_factory=list)
    #: Alternative wordings merged into this canonical claim.
    variants: list[str] = field(default_factory=list)

    # -- verification metadata (stamped by the verification engine) --------
    supporting_sources: int = 0
    independent_domains: int = 0
    #: 0..1 corroboration strength across independent sources.
    agreement: float = 0.0
    #: Ids of claims that conflict with this one.
    contradicts: list[str] = field(default_factory=list)
    status: VerificationStatus = VerificationStatus.UNVERIFIED
    #: Deterministic 0..1 confidence in the claim, with its explanation.
    confidence: float = 0.0
    confidence_explanation: str = ""
    #: Deterministic 0..1 importance to the research objective (stamped by
    #: reasoning). Not all information is equally valuable: importance ranks
    #: claims so high-impact knowledge drives answers and low-value facts
    #: don't dominate the research process.
    importance: float = 0.0


@dataclass
class Entity:
    """A discovered entity/concept (secondary node in the evidence graph)."""

    id: str
    name: str
    type: str = "concept"
    claim_ids: list[str] = field(default_factory=list)


class EdgeRelation(str, Enum):
    """Typed relationships in the evidence graph (``OBJECTIVE.md`` module 8)."""

    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    EXTENDS = "extends"
    DEPENDS_ON = "depends_on"
    DEFINES = "defines"
    REFERENCES = "references"


@dataclass
class GraphNode:
    """A node in the evidence graph. Claims are primary; the rest secondary."""

    id: str
    #: "claim" | "evidence" | "document" | "entity"
    kind: str
    label: str
    #: Id of the underlying domain object (claim id, evidence id, ...).
    ref_id: str


@dataclass
class GraphEdge:
    """A typed, directed edge between two evidence-graph nodes."""

    id: str
    source_id: str
    target_id: str
    relation: EdgeRelation = EdgeRelation.REFERENCES


@dataclass
class ConfidenceReport:
    """A deterministic confidence score plus the factors that produced it.

    Every score is explainable: the inputs are recorded alongside the result
    and summarized in ``explanation`` (``OBJECTIVE.md`` confidence model).
    """

    score: float = 0.0
    independent_sources: int = 0
    #: Mean 0..1 authority of the contributing sources.
    authority: float = 0.0
    #: Mean 0..1 cross-source agreement of the supporting claims.
    agreement: float = 0.0
    #: 0..1 fraction of the research plan covered by verified evidence.
    coverage: float = 0.0
    contradictions: int = 0
    #: Mean 0..1 relevance of the supporting evidence.
    evidence_quality: float = 0.0
    #: 0..1 fraction of supporting claims that are specific (typed, dated, numeric).
    specificity: float = 0.0
    explanation: str = ""

    @property
    def label(self) -> str:
        return confidence_label(self.score)


@dataclass
class Finding:
    """A synthesized conclusion. Every finding references verified claims."""

    id: str
    statement: str
    claim_ids: list[str] = field(default_factory=list)
    subquestion_id: str = ""
    confidence: float = 0.0
    confidence_explanation: str = ""

    @property
    def confidence_label(self) -> str:
        return confidence_label(self.confidence)


@dataclass
class Hypothesis:
    """A generated hypothesis inviting further investigation."""

    id: str
    statement: str
    claim_ids: list[str] = field(default_factory=list)
    confidence: float = 0.0

    @property
    def confidence_label(self) -> str:
        return confidence_label(self.confidence)


@dataclass
class Contradiction:
    """Conflicting claims detected during verification."""

    id: str
    description: str
    claim_ids: list[str] = field(default_factory=list)


@dataclass
class ResearchReport:
    """The rendered research artifact."""

    topic: str
    executive_summary: str
    markdown: str
    file_path: str = ""


@dataclass
class ResearchSession:
    """The complete, inspectable record of a research run.

    This object is the single source of truth for a session and is what gets
    serialized to disk, guaranteeing reports are reproducible from stored data.
    """

    id: str
    request: ResearchRequest
    status: TaskStatus = TaskStatus.PENDING
    created_at: str = ""
    completed_at: str = ""
    provider_info: dict[str, str] = field(default_factory=dict)

    plan: ResearchPlan | None = None
    tasks: list[Task] = field(default_factory=list)
    #: Every search result evaluated, accepted or not (full audit trail).
    candidates: list[SearchCandidate] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    documents: list[RawDocument] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    entities: list[Entity] = field(default_factory=list)
    graph_nodes: list[GraphNode] = field(default_factory=list)
    graph_edges: list[GraphEdge] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    hypotheses: list[Hypothesis] = field(default_factory=list)
    contradictions: list[Contradiction] = field(default_factory=list)
    #: Direct answer to the research question ("" when not answerable).
    direct_answer: str = ""
    #: The full answer object synthesized from the knowledge model.
    answer: Answer | None = None
    #: Cross-cutting patterns observed across subquestions.
    patterns: list[str] = field(default_factory=list)
    #: Evidence gaps identified by reasoning (drive the research loop).
    missing_evidence: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    confidence: ConfidenceReport | None = None
    overall_confidence: float = 0.0

    # -- agent-loop audit trail ---------------------------------------------
    #: Every search task the adaptive planner emitted, in execution order.
    search_tasks: list[SearchTask] = field(default_factory=list)
    #: Every knowledge gap curiosity discovered (investigated or still open).
    knowledge_gaps: list[KnowledgeGap] = field(default_factory=list)
    #: Per-iteration information-gain and confidence record.
    iteration_records: list[IterationRecord] = field(default_factory=list)
    #: Why research stopped (stopping-engine decision, human-readable).
    stop_reason: str = ""

    # -- research-loop / efficiency statistics -----------------------------
    #: Number of retrieval→verification iterations executed.
    iterations: int = 0
    candidates_evaluated: int = 0
    candidates_rejected: int = 0
    documents_downloaded: int = 0

    report: ResearchReport | None = None
