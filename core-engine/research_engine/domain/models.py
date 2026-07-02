"""Shared domain models.

These dataclasses are the *only* contract between subsystems. No subsystem
imports another subsystem's implementation; they exchange these types. Keeping
the models in one module makes the data flow explicit and the boundaries stable.

The flow of a session, expressed in these types::

    ResearchRequest
        -> Task[]            (planner)
        -> RawDocument[]     (collection)
        -> Source[] + Evidence[]        (processing)
        -> Entity[] + Relationship[]    (knowledge graph)
        -> Finding[] + Hypothesis[] + Contradiction[] + open_questions[] (reasoning)
        -> ResearchReport   (report)
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


def confidence_label(score: float) -> str:
    """Map a 0..1 confidence score to a coarse human label."""
    if score >= 0.66:
        return "high"
    if score >= 0.33:
        return "medium"
    return "low"


@dataclass
class ResearchRequest:
    """A user's request to research a topic."""

    topic: str
    max_subtopics: int = 6
    documents_per_query: int = 3


@dataclass
class Task:
    """A node in the research task graph."""

    id: str
    description: str
    kind: TaskKind
    query: str = ""
    depends_on: list[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    error: str | None = None


@dataclass
class Source:
    """Provenance for a piece of evidence.

    ``authority``/``authority_tier``/``domain`` are populated by the ranking
    subsystem (v0.3): a deterministic, source-quality assessment that feeds
    confidence estimation. They default to a neutral "unknown" so sources created
    outside the ranking stage remain valid.
    """

    id: str
    title: str
    provider: str
    locator: str = ""  # URL, file path, or other reference
    retrieved_at: str = ""
    #: Network domain parsed from ``locator`` (e.g. "arxiv.org"); "" if none.
    domain: str = ""
    #: 0..1 source-authority score assigned by the ranking subsystem.
    authority: float = 0.0
    #: Human-readable authority tier (e.g. "peer-reviewed", "encyclopedia").
    authority_tier: str = "unknown"


@dataclass
class RawDocument:
    """Unprocessed information acquired by the collection subsystem.

    ``relevance_score`` is assigned by the ranking subsystem before processing;
    it is 0.0 until a document has been ranked.
    """

    id: str
    query: str
    task_id: str
    title: str
    content: str
    source: Source
    #: 0..1 topical-relevance score assigned by the ranking subsystem.
    relevance_score: float = 0.0


@dataclass
class Evidence:
    """A single factual claim extracted from a source, with provenance.

    ``relevance_score`` carries the relevance of the document the claim came from,
    so downstream reasoning/confidence can weight evidence by how relevant its
    source was.
    """

    id: str
    claim: str
    source_id: str
    task_id: str
    entities: list[str] = field(default_factory=list)
    relevance_score: float = 0.0


@dataclass
class Entity:
    """A discovered entity/concept in the knowledge graph."""

    id: str
    name: str
    type: str = "concept"
    evidence_ids: list[str] = field(default_factory=list)


@dataclass
class Relationship:
    """A discovered relationship between two entities."""

    id: str
    source_entity_id: str
    target_entity_id: str
    relation: str = "related_to"
    evidence_ids: list[str] = field(default_factory=list)


@dataclass
class Finding:
    """A synthesized conclusion supported by evidence."""

    id: str
    statement: str
    supporting_evidence_ids: list[str] = field(default_factory=list)
    confidence: float = 0.0

    @property
    def confidence_label(self) -> str:
        return confidence_label(self.confidence)


@dataclass
class Hypothesis:
    """A generated hypothesis inviting further investigation."""

    id: str
    statement: str
    supporting_evidence_ids: list[str] = field(default_factory=list)
    confidence: float = 0.0

    @property
    def confidence_label(self) -> str:
        return confidence_label(self.confidence)


@dataclass
class ClaimCluster:
    """A group of equivalent claims asserted by one or more sources.

    Clustering equivalent claims lets the engine measure *agreement*: a claim
    corroborated by several independent sources/domains is stronger than a
    single-sourced one. Produced by the verification subsystem (v0.3).
    """

    id: str
    canonical_claim: str
    evidence_ids: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)
    #: Number of distinct sources asserting the claim.
    supporting_sources: int = 0
    #: Number of distinct network domains asserting the claim (independence).
    independent_domains: int = 0
    #: 0..1 agreement strength derived from corroboration across sources.
    agreement: float = 0.0


@dataclass
class Contradiction:
    """Conflicting evidence detected during processing/reasoning."""

    id: str
    description: str
    evidence_ids: list[str] = field(default_factory=list)


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

    tasks: list[Task] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    raw_documents: list[RawDocument] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    claim_clusters: list[ClaimCluster] = field(default_factory=list)
    entities: list[Entity] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    hypotheses: list[Hypothesis] = field(default_factory=list)
    contradictions: list[Contradiction] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    overall_confidence: float = 0.0
    #: Count of retrieved documents rejected by relevance filtering (v0.3).
    #: A measure of evidence-pollution avoided and tokens saved.
    rejected_documents: int = 0

    report: ResearchReport | None = None
