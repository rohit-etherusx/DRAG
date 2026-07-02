"""Research state.

The single source of truth for a running research session (``ARCHITECTURE.md``
v0.5). Every module reads the current state of research from this object and
writes its results back through the mutation methods below — no research
information lives anywhere else while a run is in progress.

The state tracks:

* the research plan and the lifecycle of its subquestions (active/completed);
* search history (executed queries, emitted search tasks, failures) and
  visited URLs, so the agent never repeats work;
* everything acquired so far: candidates, sources, documents, evidence,
  extracted claims;
* the knowledge model: verified claims, contradictions, entities, and the
  evidence graph;
* knowledge gaps discovered by the curiosity engine (the fuel of the loop);
* per-iteration information-gain records and the confidence history the
  stopping engine reads.

When the run ends, :meth:`to_session` renders the persistent
:class:`ResearchSession` snapshot from the state — the session is a *view* of
the state, never a second copy maintained in parallel.
"""
from __future__ import annotations

from research_engine.domain.models import (
    Claim,
    Contradiction,
    Entity,
    Evidence,
    GraphEdge,
    GraphNode,
    IterationRecord,
    KnowledgeGap,
    RawDocument,
    ResearchPlan,
    ResearchRequest,
    ResearchSession,
    SearchCandidate,
    SearchTask,
    Source,
    Task,
    TaskStatus,
)
from research_engine.processing.extraction import ExtractedClaim


class ResearchState:
    """Mutable state of one research run; mutated only through its methods."""

    def __init__(
        self,
        session_id: str,
        request: ResearchRequest,
        plan: ResearchPlan,
        tasks: list[Task],
        created_at: str = "",
        provider_info: dict[str, str] | None = None,
    ) -> None:
        self.session_id = session_id
        self.request = request
        self.plan = plan
        self.tasks = tasks

        # -- subquestion lifecycle ------------------------------------------
        self._active_subquestions: set[str] = {sq.id for sq in plan.subquestions}
        self._completed_subquestions: dict[str, str] = {}  # id -> reason

        # -- search history --------------------------------------------------
        self._executed_queries: set[str] = set()
        self.search_tasks: list[SearchTask] = []
        self.failed_searches: list[str] = []
        self._visited_urls: set[str] = set()

        # -- acquisition ------------------------------------------------------
        self.candidates: list[SearchCandidate] = []
        self.candidates_evaluated = 0
        self.candidates_rejected = 0
        self.documents: list[RawDocument] = []
        self.documents_downloaded = 0
        self.sources_by_id: dict[str, Source] = {}
        self.evidence: list[Evidence] = []
        self.extracted_claims: list[ExtractedClaim] = []

        # -- knowledge model ---------------------------------------------------
        self.claims: list[Claim] = []
        self.contradictions: list[Contradiction] = []
        self.entities: list[Entity] = []
        self.graph_nodes: list[GraphNode] = []
        self.graph_edges: list[GraphEdge] = []

        # -- research intelligence --------------------------------------------
        self.gaps: list[KnowledgeGap] = []
        self._gap_keys: dict[str, KnowledgeGap] = {}
        self.iteration_records: list[IterationRecord] = []
        self.confidence_history: list[float] = []
        self.stop_reason: str = ""

        # -- session metadata ---------------------------------------------------
        self._created_at = created_at
        self._provider_info = provider_info or {}

    # -- subquestion lifecycle ------------------------------------------------

    @property
    def active_subquestion_ids(self) -> set[str]:
        """Subquestions still open for investigation."""
        return set(self._active_subquestions)

    def complete_subquestion(self, subquestion_id: str, reason: str) -> None:
        """Terminate a research branch that has been satisfied.

        A completed subquestion no longer receives search tasks; the reason is
        kept so the decision is explainable.
        """
        if subquestion_id in self._active_subquestions:
            self._active_subquestions.discard(subquestion_id)
            self._completed_subquestions[subquestion_id] = reason

    @property
    def completed_subquestions(self) -> dict[str, str]:
        return dict(self._completed_subquestions)

    # -- search history ---------------------------------------------------------

    def was_query_executed(self, query: str) -> bool:
        return _normalize_query(query) in self._executed_queries

    def record_search_task(self, task: SearchTask) -> None:
        """Register an emitted search task and remember its query."""
        self.search_tasks.append(task)
        self._executed_queries.add(_normalize_query(task.query))

    def record_search_failure(self, description: str) -> None:
        self.failed_searches.append(description)

    def is_visited(self, url: str) -> bool:
        return url in self._visited_urls

    def mark_visited(self, url: str) -> None:
        if url:
            self._visited_urls.add(url)

    @property
    def visited_urls(self) -> frozenset[str]:
        return frozenset(self._visited_urls)

    # -- acquisition ---------------------------------------------------------------

    def add_candidates(self, candidates: list[SearchCandidate]) -> None:
        """Record evaluated candidates (accepted or not) in the audit trail."""
        self.candidates.extend(candidates)
        self.candidates_evaluated += len(candidates)
        self.candidates_rejected += sum(1 for c in candidates if not c.accepted)
        for candidate in candidates:
            self.mark_visited(candidate.url or candidate.id)

    def add_documents(self, documents: list[RawDocument]) -> None:
        self.documents.extend(documents)
        self.documents_downloaded += len(documents)
        for document in documents:
            self.sources_by_id.setdefault(document.source.id, document.source)

    def add_evidence(self, evidence: list[Evidence]) -> None:
        self.evidence.extend(evidence)

    def add_extracted_claims(self, claims: list[ExtractedClaim]) -> None:
        self.extracted_claims.extend(claims)

    # -- knowledge model --------------------------------------------------------

    def set_knowledge(
        self,
        claims: list[Claim],
        contradictions: list[Contradiction],
        entities: list[Entity],
        graph_nodes: list[GraphNode],
        graph_edges: list[GraphEdge],
    ) -> None:
        """Replace the knowledge model after a knowledge-builder update."""
        self.claims = claims
        self.contradictions = contradictions
        self.entities = entities
        self.graph_nodes = graph_nodes
        self.graph_edges = graph_edges

    # -- knowledge gaps ------------------------------------------------------------

    def add_gaps(self, gaps: list[KnowledgeGap]) -> list[KnowledgeGap]:
        """Merge newly discovered gaps into the state.

        Gaps are identified by (kind, subquestion, entity): re-discovering a
        known gap never duplicates it (and never resets its ``investigated``
        flag). Returns the gaps that were genuinely new.
        """
        new: list[KnowledgeGap] = []
        for gap in gaps:
            key = f"{gap.kind.value}|{gap.subquestion_id}|{gap.entity.lower()}"
            if key in self._gap_keys:
                continue
            gap.id = f"gap-{len(self._gap_keys) + 1}"
            self._gap_keys[key] = gap
            self.gaps.append(gap)
            new.append(gap)
        return new

    def open_gaps(self) -> list[KnowledgeGap]:
        """Uninvestigated gaps, highest priority first (stable order)."""
        return sorted(
            (g for g in self.gaps if not g.investigated),
            key=lambda g: (-g.priority, g.id),
        )

    def mark_gap_investigated(self, gap_id: str) -> None:
        for gap in self.gaps:
            if gap.id == gap_id:
                gap.investigated = True
                return

    # -- iterations ----------------------------------------------------------------

    def record_iteration(self, record: IterationRecord) -> None:
        self.iteration_records.append(record)
        self.confidence_history.append(record.confidence)

    @property
    def iteration(self) -> int:
        """The number of completed iterations."""
        return len(self.iteration_records)

    # -- session rendering ---------------------------------------------------------

    def to_session(self) -> ResearchSession:
        """Render the persistent session snapshot from the current state.

        Reasoning outputs (findings, answer, confidence, report) are attached
        by the orchestrator after the loop; this method covers everything the
        state owns.
        """
        session = ResearchSession(
            id=self.session_id,
            request=self.request,
            status=TaskStatus.IN_PROGRESS,
            created_at=self._created_at,
            provider_info=dict(self._provider_info),
        )
        session.plan = self.plan
        session.tasks = self.tasks
        session.candidates = self.candidates
        session.sources = list(self.sources_by_id.values())
        session.documents = self.documents
        session.evidence = self.evidence
        session.claims = self.claims
        session.entities = self.entities
        session.graph_nodes = self.graph_nodes
        session.graph_edges = self.graph_edges
        session.contradictions = self.contradictions
        session.search_tasks = self.search_tasks
        session.knowledge_gaps = self.gaps
        session.iteration_records = self.iteration_records
        session.stop_reason = self.stop_reason
        session.iterations = self.iteration
        session.candidates_evaluated = self.candidates_evaluated
        session.candidates_rejected = self.candidates_rejected
        session.documents_downloaded = self.documents_downloaded
        return session


def _normalize_query(query: str) -> str:
    return " ".join(query.lower().split())


__all__ = ["ResearchState"]
