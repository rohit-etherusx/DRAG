"""Research orchestrator.

The central coordinator. It owns the research lifecycle — planning, executing
the task graph, collecting and processing evidence, building the knowledge
graph, reasoning, generating the report, and persisting the session — while
containing no domain-specific logic. Task failures are handled explicitly:
a failed collection task is recorded and the run continues.
"""
from __future__ import annotations

from research_engine.collection.collector import EvidenceCollector
from research_engine.config import EngineConfig
from research_engine.domain.models import (
    ResearchRequest,
    ResearchSession,
    Source,
    TaskKind,
    TaskStatus,
)
from research_engine.knowledge.graph import KnowledgeGraph
from research_engine.logging_setup import get_logger
from research_engine.planner.planner import ResearchPlanner
from research_engine.processing.extraction import build_extractor
from research_engine.processing.processor import EvidenceProcessor
from research_engine.providers.base import LLMProvider, SearchProvider
from research_engine.ranking.ranker import build_ranker
from research_engine.reasoning.analyzer import ReasoningEngine
from research_engine.report.generator import ReportGenerator
from research_engine.verification.verifier import EvidenceVerifier
from research_engine.storage.storage import SessionStorage
from research_engine.utils import keywords, slugify, utc_now_iso

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

        self._planner = ResearchPlanner()
        self._reasoner = ReasoningEngine(llm_provider)
        self._report_generator = ReportGenerator()

    def run(self, request: ResearchRequest) -> ResearchSession:
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
        _log.info("Starting research session for topic: %s", request.topic)

        graph = self._planner.plan(request)
        session.tasks = graph.topological_order()

        topic_keywords = keywords(request.topic)
        collector = EvidenceCollector(self._search, request.documents_per_query)
        ranker = build_ranker(
            self._config, request.topic, topic_keywords, llm=self._llm
        )
        extractor = build_extractor(
            self._llm,
            request.topic,
            topic_keywords,
            enabled=self._config.llm_enabled,
        )
        processor = EvidenceProcessor(extractor=extractor)
        sources_by_id: dict[str, Source] = {}

        # Execute collection tasks in dependency order. Each task's documents pass
        # through the ranking gate (relevance + authority scoring, filtering,
        # passage selection) before processing, so only genuinely relevant,
        # trimmed evidence reaches extraction and the knowledge graph.
        for task in session.tasks:
            if task.kind is not TaskKind.COLLECT:
                continue
            task.status = TaskStatus.IN_PROGRESS
            try:
                documents = collector.collect(task)
                session.raw_documents.extend(documents)
                outcome = ranker.rank(documents)
                session.rejected_documents += outcome.rejected
                # Only accepted sources contribute provenance to the graph/report.
                for document in outcome.accepted:
                    sources_by_id.setdefault(document.source.id, document.source)
                session.evidence.extend(processor.process(outcome.accepted))
                task.status = TaskStatus.COMPLETED
                _log.info(
                    "Task %s collected %d, accepted %d, rejected %d document(s)",
                    task.id,
                    len(documents),
                    len(outcome.accepted),
                    outcome.rejected,
                )
            except Exception as exc:  # keep the session resilient to a bad source
                task.status = TaskStatus.FAILED
                task.error = str(exc)
                _log.warning("Task %s failed: %s", task.id, exc)

        session.sources = list(sources_by_id.values())
        session.contradictions = processor.detect_contradictions(session.evidence)

        # Verify: cluster equivalent claims across sources so corroboration
        # (agreement) can strengthen confidence and be reported explicitly.
        verification = None
        if self._config.verification_enabled:
            verification = EvidenceVerifier().verify(session.evidence, sources_by_id)
            session.claim_clusters = verification.clusters
            _log.info(
                "Verification: %d claim cluster(s), %d corroborated by 2+ sources",
                len(verification.clusters),
                verification.corroborated_clusters,
            )

        # Build the knowledge graph: entity co-occurrence plus any explicit
        # relationships the LLM extracted from the sources.
        knowledge_graph = KnowledgeGraph()
        knowledge_graph.build(session.evidence)
        knowledge_graph.add_extracted_relationships(processor.relationships)
        session.entities = knowledge_graph.entities
        session.relationships = knowledge_graph.relationships

        # Reason over structured evidence (the synthesis task).
        result = self._reasoner.analyze(
            topic=request.topic,
            tasks=session.tasks,
            evidence=session.evidence,
            knowledge_graph=knowledge_graph,
            contradictions=session.contradictions,
            documents_per_query=request.documents_per_query,
            sources=sources_by_id,
            verification=verification,
        )
        session.findings = result.findings
        session.hypotheses = result.hypotheses
        session.open_questions = result.open_questions
        session.suggestions = result.suggestions
        session.overall_confidence = result.overall_confidence
        for task in session.tasks:
            if task.kind is TaskKind.SYNTHESIZE:
                task.status = TaskStatus.COMPLETED

        # Generate and persist the report.
        session.report = self._report_generator.generate(
            session, result.executive_summary
        )
        session.status = TaskStatus.COMPLETED
        session.completed_at = utc_now_iso()

        report_path = self._storage.save_report(session)
        self._storage.save_session(session)
        _log.info("Report written to %s", report_path)
        return session
