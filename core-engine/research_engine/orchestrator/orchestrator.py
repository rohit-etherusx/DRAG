"""Research orchestrator.

The central coordinator. It owns the claim-centric research lifecycle:

    plan → targeted retrieval → candidate evaluation → download → passage
    extraction → claim extraction → normalization → verification → evidence
    graph → reasoning → adaptive report → persistence

wrapped in the **research loop** (``OBJECTIVE.md``): when overall confidence
stays below the configured threshold, the engine identifies the subquestions
with missing or uncorroborated evidence, generates follow-up searches for
them, and repeats retrieval and verification — terminating only when the
threshold is reached, the gaps are closed, or the search budget
(``max_iterations``) is exhausted.

The orchestrator contains no domain-specific logic, and failures are handled
explicitly: a failed subquestion is recorded on its task and the run continues.
"""
from __future__ import annotations

from research_engine.collection.collector import RetrievalManager
from research_engine.config import EngineConfig
from research_engine.domain.models import (
    ResearchRequest,
    ResearchSession,
    Source,
    TaskKind,
    TaskStatus,
)
from research_engine.knowledge.graph import EvidenceGraph
from research_engine.logging_setup import get_logger
from research_engine.planner.planner import ResearchPlanner
from research_engine.processing.extraction import ExtractedClaim, build_extractor
from research_engine.processing.normalizer import ClaimNormalizer
from research_engine.processing.processor import EvidenceProcessor
from research_engine.providers.base import LLMProvider, SearchProvider
from research_engine.ranking.evaluator import CandidateEvaluator
from research_engine.ranking.passages import PassageSelector
from research_engine.reasoning.analyzer import ReasoningEngine, ReasoningResult
from research_engine.report.generator import ReportGenerator
from research_engine.storage.storage import SessionStorage
from research_engine.utils import keywords, slugify, utc_now_iso
from research_engine.verification.verifier import ClaimVerifier

_log = get_logger("orchestrator")


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
        session = ResearchSession(
            id=f"session-{slugify(request.topic)}",
            request=request,
            status=TaskStatus.IN_PROGRESS,
            created_at=utc_now_iso(),
            provider_info={
                "search_provider": self._search.name,
                "llm_provider": self._llm.name,
            },
        )
        _log.info("Starting research session for: %s", request.topic)

        # 1. Understand the question before searching.
        planner = ResearchPlanner(llm)
        plan = planner.plan(request)
        session.plan = plan
        session.tasks = planner.tasks_for(plan).topological_order()
        collect_tasks = {
            task.subquestion_id: task
            for task in session.tasks
            if task.kind is TaskKind.COLLECT
        }
        _log.info(
            "Plan (%s): %d subquestion(s) for objective: %s",
            plan.planner, len(plan.subquestions), plan.objective,
        )

        # 2. Assemble the pipeline stages.
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
        verifier = ClaimVerifier()
        reasoner = ReasoningEngine(llm)

        # 3. The research loop.
        sources_by_id: dict[str, Source] = {}
        extracted: list[ExtractedClaim] = []
        result: ReasoningResult | None = None
        evidence_graph = EvidenceGraph()
        target_ids = {sq.id for sq in plan.subquestions}
        max_iterations = max(1, config.max_iterations)

        for iteration in range(1, max_iterations + 1):
            session.iterations = iteration
            self._collect(
                session, plan, planner, retrieval, evaluator, processor,
                sources_by_id, extracted, collect_tasks, target_ids, iteration,
            )

            # Normalize + verify the full accumulated claim set, then reason.
            session.sources = list(sources_by_id.values())
            evidence_by_id = {e.id: e for e in session.evidence}
            claims = normalizer.normalize(extracted, evidence_by_id)
            if config.verification_enabled:
                verification = verifier.verify(claims, sources_by_id)
                claims = verification.claims
                session.contradictions = verification.contradictions
                _log.info(
                    "Verification: %d claim(s), %d corroborated, %d unsupported",
                    len(claims),
                    verification.corroborated_claims,
                    verification.unsupported_claims,
                )
            else:
                session.contradictions = []
            session.claims = claims

            evidence_graph = EvidenceGraph()
            evidence_graph.build(claims, session.evidence)

            result = reasoner.analyze(
                plan=plan,
                claims=claims,
                graph=evidence_graph,
                contradictions=session.contradictions,
                sources=sources_by_id,
                evidence=session.evidence,
            )

            if result.confidence.score >= config.confidence_threshold:
                _log.info(
                    "Confidence %.0f%% reached threshold %.0f%% at iteration %d",
                    result.confidence.score * 100,
                    config.confidence_threshold * 100,
                    iteration,
                )
                break
            target_ids = set(result.weak_subquestion_ids)
            if not target_ids or iteration == max_iterations:
                _log.info(
                    "Stopping at iteration %d (confidence %.0f%%): %s",
                    iteration,
                    result.confidence.score * 100,
                    "no actionable gaps" if not target_ids else "budget exhausted",
                )
                break
            _log.info(
                "Confidence %.0f%% below threshold; iterating on %d weak "
                "subquestion(s)",
                result.confidence.score * 100,
                len(target_ids),
            )

        # 4. Populate the session from the final reasoning pass.
        assert result is not None  # loop always runs at least once
        session.entities = evidence_graph.entities
        session.graph_nodes = evidence_graph.nodes
        session.graph_edges = evidence_graph.edges
        session.findings = result.findings
        session.hypotheses = result.hypotheses
        session.direct_answer = result.direct_answer
        session.patterns = result.patterns
        session.missing_evidence = result.missing_evidence
        session.open_questions = result.open_questions
        session.suggestions = result.suggestions
        session.confidence = result.confidence
        session.overall_confidence = result.confidence.score
        for task in session.tasks:
            if task.kind is TaskKind.SYNTHESIZE:
                task.status = TaskStatus.COMPLETED

        # 5. Generate and persist the report.
        session.report = self._report_generator.generate(
            session, result.executive_summary
        )
        session.status = TaskStatus.COMPLETED
        session.completed_at = utc_now_iso()

        report_path = self._storage.save_report(session)
        self._storage.save_session(session)
        _log.info("Report written to %s", report_path)
        return session

    def _collect(
        self,
        session: ResearchSession,
        plan,
        planner: ResearchPlanner,
        retrieval: RetrievalManager,
        evaluator: CandidateEvaluator,
        processor: EvidenceProcessor,
        sources_by_id: dict[str, Source],
        extracted: list[ExtractedClaim],
        collect_tasks: dict,
        target_ids: set[str],
        iteration: int,
    ) -> None:
        """One retrieval pass over the targeted subquestions.

        Each subquestion is isolated: retrieval → candidate evaluation →
        download → passage extraction → claim extraction, with any failure
        recorded on the subquestion's task without aborting the run.
        """
        for subquestion in plan.subquestions:
            if subquestion.id not in target_ids:
                continue
            task = collect_tasks.get(subquestion.id)
            if task is None:
                continue
            task.status = TaskStatus.IN_PROGRESS
            try:
                queries = (
                    None
                    if iteration == 1
                    else planner.follow_up_queries(plan, subquestion, iteration)
                )
                candidates = retrieval.retrieve(subquestion, task, queries)
                outcome = evaluator.evaluate(candidates, subquestion.question)
                session.candidates.extend(candidates)
                session.candidates_evaluated += len(candidates)
                session.candidates_rejected += len(outcome.rejected)

                documents = retrieval.download(outcome.accepted)
                session.documents.extend(documents)
                session.documents_downloaded += len(documents)
                for document in documents:
                    sources_by_id.setdefault(document.source.id, document.source)

                evidence, claims = processor.process(
                    documents, subquestion.question
                )
                session.evidence.extend(evidence)
                extracted.extend(claims)
                task.status = TaskStatus.COMPLETED
                _log.info(
                    "%s (iter %d): %d candidate(s), %d accepted, %d downloaded, "
                    "%d passage(s), %d claim(s)",
                    subquestion.id, iteration, len(candidates),
                    len(outcome.accepted), len(documents), len(evidence),
                    len(claims),
                )
            except Exception as exc:  # keep the session resilient to a bad source
                task.status = TaskStatus.FAILED
                task.error = str(exc)
                _log.warning("Subquestion %s failed: %s", subquestion.id, exc)
