"""Research orchestrator.

The central coordinator of the autonomous research agent (``ARCHITECTURE.md``
v0.5). It owns the lifecycle, execution order, iteration control, and stopping
— and nothing else: no search logic, no extraction logic, no report logic.

Each run is an iterative learning process over a single
:class:`ResearchState`:

    plan → research state
    ┌─► adaptive planning   (search tasks from the plan, then from gaps)
    │       ↓
    │   acquisition         (search → candidate gate → download → passages
    │       ↓                → typed claims)
    │   knowledge update    (normalize → verify → build graph → importance)
    │       ↓
    │   reasoning           (findings, confidence — every iteration)
    │       ↓
    │   curiosity           (knowledge gaps → fuel for the next iteration)
    │       ↓
    │   information gain    (what this iteration actually taught the engine)
    │       ↓
    └── stopping decision   (explicit, recorded reason)
            ↓
    answer generation       (from the completed knowledge model)
            ↓
    report rendering + persistence

Failures are handled explicitly at every stage: a failed search task is
recorded in the state and the run continues.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from research_engine.collection.collector import RetrievalManager
from research_engine.concurrency import parallel_map
from research_engine.config import EngineConfig
from research_engine.domain.models import (
    Evidence,
    RawDocument,
    ResearchRequest,
    ResearchSession,
    SearchCandidate,
    SearchTask,
    Task,
    TaskKind,
    TaskStatus,
)
from research_engine.knowledge.builder import KnowledgeBuilder
from research_engine.logging_setup import get_logger
from research_engine.planner.planner import ResearchPlanner
from research_engine.processing.extraction import build_extractor
from research_engine.processing.normalizer import ClaimNormalizer
from research_engine.processing.processor import EvidenceProcessor
from research_engine.providers.base import LLMProvider, SearchProvider
from research_engine.ranking.evaluator import CandidateEvaluator
from research_engine.ranking.passages import PassageSelector
from research_engine.reasoning.analyzer import ReasoningEngine, ReasoningResult
from research_engine.reasoning.answer import AnswerGenerator
from research_engine.reasoning.curiosity import CuriosityEngine
from research_engine.reasoning.gain import InformationGainAnalyzer
from research_engine.reasoning.importance import ImportanceModel
from research_engine.reasoning.stopping import StoppingEngine
from research_engine.report.generator import ReportGenerator
from research_engine.state.research_state import ResearchState
from research_engine.storage.storage import SessionStorage
from research_engine.utils import keywords, slugify, utc_now_iso
from research_engine.verification.equivalence import LLMEquivalenceJudge
from research_engine.verification.verifier import ClaimVerifier

_log = get_logger("orchestrator")


@dataclass
class _Fetched:
    """One search task's pure acquisition result (no research-state writes).

    Produced concurrently in the acquisition fan-out; consumed sequentially, in
    task order, by the deterministic merge. ``error`` is set instead of raising
    so one failing task never aborts the batch.
    """

    search_task: SearchTask
    candidates: list[SearchCandidate] = field(default_factory=list)
    accepted: int = 0
    documents: list[RawDocument] = field(default_factory=list)
    error: Exception | None = None


class ResearchOrchestrator:
    """Runs a complete research session from request to persisted report."""

    def __init__(
        self,
        config: EngineConfig,
        search_provider: SearchProvider,
        llm_provider: LLMProvider,
        storage: SessionStorage,
    ) -> None:
        self._config = config
        self._search = search_provider
        self._llm = llm_provider
        self._storage = storage
        self._report_generator = ReportGenerator()

    def run(self, request: ResearchRequest) -> ResearchSession:
        config = self._config
        llm = self._llm if config.llm_enabled else None

        # 1. Understand the question before searching; initialize the state.
        planner = ResearchPlanner(llm)
        plan = planner.plan(request)
        state = ResearchState(
            session_id=f"session-{slugify(request.topic)}",
            request=request,
            plan=plan,
            tasks=planner.tasks_for(plan).topological_order(),
            created_at=utc_now_iso(),
            provider_info={
                "search_provider": self._search.name,
                "llm_provider": self._llm.name,
            },
        )
        _log.info("Starting research session for: %s", request.topic)
        _log.info(
            "Plan (%s): %d subquestion(s) for objective: %s",
            plan.planner, len(plan.subquestions), plan.objective,
        )

        # 2. Assemble the pipeline around the state.
        retrieval = RetrievalManager(self._search, config.max_candidates_per_query)
        evaluator = CandidateEvaluator(
            plan,
            relevance_threshold=config.candidate_relevance_threshold,
            min_authority=config.min_authority,
            max_accepted=request.documents_per_query,
            enabled=config.evaluation_enabled,
        )
        processor = EvidenceProcessor(
            extractor=build_extractor(
                llm,
                plan.objective,
                keywords(plan.subject),
                enabled=config.llm_enabled,
            ),
            selector=PassageSelector(
                max_passages=config.max_passages,
                min_relevance=config.passage_min_relevance,
            ),
        )
        normalizer = ClaimNormalizer()
        verifier = ClaimVerifier(
            judge=LLMEquivalenceJudge(llm) if llm is not None else None,
            max_equivalence_checks=config.max_equivalence_checks,
        )
        builder = KnowledgeBuilder()
        importance = ImportanceModel()
        reasoner = ReasoningEngine(llm)
        curiosity = CuriosityEngine()
        gain = InformationGainAnalyzer()
        stopping = StoppingEngine(
            confidence_threshold=config.confidence_threshold,
            min_iteration_gain=config.min_iteration_gain,
            min_confidence_delta=config.min_confidence_delta,
            max_iterations=config.max_iterations,
        )
        answer_generator = AnswerGenerator(llm)

        # 3. The agent loop: search → knowledge update → reason → gaps → stop?
        collect_tasks = {
            task.subquestion_id: task
            for task in state.tasks
            if task.kind is TaskKind.COLLECT
        }
        result: ReasoningResult | None = None
        graph = None
        for iteration in range(1, max(1, config.max_iterations) + 1):
            search_tasks = planner.next_search_tasks(
                state, iteration, config.max_search_tasks_per_iteration
            )
            if not search_tasks:
                state.stop_reason = (
                    "the planner found no further searches worth running"
                )
                _log.info("Stopping before iteration %d: %s",
                          iteration, state.stop_reason)
                break
            _log.info(
                "Iteration %d: %d search task(s) (%s)",
                iteration,
                len(search_tasks),
                "initial plan" if iteration == 1 else "knowledge gaps",
            )

            prior_extracted = list(state.extracted_claims)
            claims_before = len(state.claims)
            new_documents = self._acquire(
                state, search_tasks, retrieval, evaluator, processor,
                collect_tasks, iteration,
            )

            # Knowledge update over the full accumulated evidence.
            evidence_by_id = {e.id: e for e in state.evidence}
            claims = normalizer.normalize(state.extracted_claims, evidence_by_id)
            if config.verification_enabled:
                verification = verifier.verify(claims, state.sources_by_id)
                claims = verification.claims
                contradictions = verification.contradictions
                corroborated = verification.corroborated_claims
                _log.info(
                    "Verification: %d claim(s), %d corroborated, %d unsupported",
                    len(claims), corroborated, verification.unsupported_claims,
                )
            else:
                contradictions, corroborated = [], 0
            graph = builder.build(claims, state.evidence)
            importance.stamp(claims, plan, graph.entities)
            state.set_knowledge(
                claims, contradictions, graph.entities, graph.nodes, graph.edges
            )

            # Reason over the important claims (low-value facts must not
            # dominate; fail open if the filter would empty the set).
            reasoning_claims = [
                c for c in claims if c.importance >= config.min_claim_importance
            ] or claims
            result = reasoner.analyze(
                plan=plan,
                claims=reasoning_claims,
                graph=graph,
                contradictions=contradictions,
                sources=state.sources_by_id,
                evidence=state.evidence,
            )

            # Curiosity: what is still missing becomes next iteration's fuel.
            new_gaps = state.add_gaps(
                curiosity.discover(
                    plan=plan,
                    claims=claims,
                    contradictions=contradictions,
                    entities=graph.entities,
                    sources=state.sources_by_id,
                    active_subquestion_ids=state.active_subquestion_ids,
                )
            )

            # Information gain: what did this iteration actually teach us?
            new_extracted = state.extracted_claims[len(prior_extracted):]
            record = gain.analyze(
                iteration=iteration,
                search_tasks=len(search_tasks),
                new_documents=new_documents,
                new_extracted=new_extracted,
                prior_extracted=prior_extracted,
                evidence_by_id=evidence_by_id,
                open_subquestion_ids=state.active_subquestion_ids,
                verified_claims=claims,
                claims_before=claims_before,
                corroborated=corroborated,
                confidence=result.confidence.score,
                gaps_open=len(state.open_gaps()),
            )
            state.record_iteration(record)
            _log.info(
                "Iteration %d: novelty %.0f%%, knowledge gain %.0f%%, "
                "confidence %.0f%%, %d new gap(s), %d open",
                iteration, record.novelty * 100, record.knowledge_gain * 100,
                record.confidence * 100, len(new_gaps), record.gaps_open,
            )

            decision = stopping.decide(state)
            if decision.stop:
                state.stop_reason = decision.reason
                _log.info("Stopping after iteration %d: %s",
                          iteration, decision.reason)
                break
            _log.info("Continuing research: %s", decision.reason)

        # 4. Answer from the completed knowledge model; render; persist.
        session = state.to_session()
        if result is not None:
            answer = answer_generator.generate(
                plan=plan,
                claims=state.claims,
                confidence=result.confidence,
                open_gaps=state.open_gaps(),
            )
            summary = answer_generator.executive_summary(
                plan, result.findings, answer, result.confidence
            )
            session.findings = result.findings
            session.hypotheses = result.hypotheses
            session.patterns = result.patterns
            session.missing_evidence = result.missing_evidence
            session.open_questions = result.open_questions
            session.suggestions = result.suggestions
            session.confidence = result.confidence
            session.overall_confidence = result.confidence.score
            session.answer = answer
            session.direct_answer = answer.text
        else:  # the loop never ran a full pass (no search tasks at all)
            summary = (
                f"Research on '{plan.question}' produced no executable "
                f"searches; no evidence was collected."
            )
        for task in session.tasks:
            if task.kind is TaskKind.SYNTHESIZE:
                task.status = TaskStatus.COMPLETED

        session.report = self._report_generator.generate(session, summary)
        session.status = TaskStatus.COMPLETED
        session.completed_at = utc_now_iso()

        report_path = self._storage.save_report(session)
        self._storage.save_session(session)
        _log.info("Report written to %s", report_path)
        return session

    def _acquire(
        self,
        state: ResearchState,
        search_tasks: list[SearchTask],
        retrieval: RetrievalManager,
        evaluator: CandidateEvaluator,
        processor: EvidenceProcessor,
        collect_tasks: dict[str, Task],
        iteration: int,
    ) -> list[RawDocument]:
        """Execute one iteration's search tasks against the state.

        Concurrency with preserved determinism. The independent, network-bound
        work — per-task search + candidate evaluation + download, then per-
        document claim extraction — runs on a bounded thread pool; every write
        to the single-source-of-truth research state happens on this thread, in
        task order. Any per-task failure is recorded on the state (and the
        subquestion's collect task) without aborting the iteration. Returns the
        documents acquired this iteration.

        Stages:
          1. fan-out (parallel): search → evaluate → download, per task, pure;
          2. merge (sequential, task order): record candidates/documents,
             de-duplicate documents, extract passages (order-dependent, so it
             stays sequential);
          3. fan-out (parallel): claim extraction per document, pure;
          4. merge (sequential, order-preserving): record extracted claims.
        """
        max_workers = self._config.max_workers
        # A single visited-URL snapshot for the whole fan-out; cross-task
        # duplicates are removed deterministically in the merge below.
        visited = state.visited_urls

        def fetch(search_task: SearchTask) -> _Fetched:
            collect_task = collect_tasks.get(search_task.subquestion_id)
            try:
                candidates = retrieval.search(
                    search_task,
                    visited,
                    collect_task.id if collect_task else "",
                )
                outcome = evaluator.evaluate(candidates, search_task.objective)
                documents = retrieval.download(outcome.accepted)
                return _Fetched(
                    search_task, candidates, len(outcome.accepted), documents
                )
            except Exception as exc:  # captured, not raised: isolate one bad task
                return _Fetched(search_task, error=exc)

        results = parallel_map(fetch, search_tasks, max_workers)

        # Merge (sequential, task order) — the only place state is mutated.
        acquired: list[RawDocument] = []
        pending: list[tuple[RawDocument, list[Evidence], _Fetched]] = []
        seen_source_ids: set[str] = set(state.sources_by_id)
        for fetched in results:
            search_task = fetched.search_task
            collect_task = collect_tasks.get(search_task.subquestion_id)
            if collect_task is not None:
                collect_task.status = TaskStatus.IN_PROGRESS
            if fetched.error is not None:
                state.record_search_failure(
                    f"{search_task.id} ({search_task.query!r}): {fetched.error}"
                )
                if collect_task is not None:
                    collect_task.status = TaskStatus.FAILED
                    collect_task.error = str(fetched.error)
                _log.warning(
                    "Search task %s failed: %s", search_task.id, fetched.error
                )
                continue
            state.add_candidates(fetched.candidates)
            # The fan-out shared one visited snapshot, so two tasks can accept
            # the same URL; keep the first (task order) and drop later repeats.
            fresh_docs: list[RawDocument] = []
            for document in fetched.documents:
                if document.source.id in seen_source_ids:
                    continue
                seen_source_ids.add(document.source.id)
                fresh_docs.append(document)
            state.add_documents(fresh_docs)
            acquired.extend(fresh_docs)
            passages = processor.extract_passages(fresh_docs, search_task.objective)
            for document, evidence in passages:
                state.add_evidence(evidence)
                pending.append((document, evidence, fetched))
            _log.info(
                "%s (iter %d): %d candidate(s), %d accepted, %d downloaded, "
                "%d passage(s)",
                search_task.id, iteration, len(fetched.candidates),
                fetched.accepted, len(fresh_docs),
                sum(len(ev) for _d, ev in passages),
            )

        # Claim extraction (parallel) then merge (sequential, order-preserving).
        extracted = parallel_map(
            lambda item: processor.extract_claims(item[0], item[1]),
            pending,
            max_workers,
        )
        claim_count = 0
        for claims in extracted:
            state.add_extracted_claims(claims)
            claim_count += len(claims)

        # A collect task completes once its subquestion's tasks all succeeded.
        for fetched in results:
            collect_task = collect_tasks.get(fetched.search_task.subquestion_id)
            if (
                collect_task is not None
                and fetched.error is None
                and collect_task.status is TaskStatus.IN_PROGRESS
            ):
                collect_task.status = TaskStatus.COMPLETED
        _log.info(
            "Iteration %d acquisition: %d document(s), %d claim(s) extracted",
            iteration, len(acquired), claim_count,
        )
        return acquired
