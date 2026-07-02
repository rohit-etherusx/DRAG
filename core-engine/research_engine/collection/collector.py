"""Retrieval manager.

Executes the search tasks the adaptive planner emits: one provider search per
task, candidates de-duplicated against everything the session has already
seen. Downloading is a separate step that operates only on candidates accepted
by the evaluation gate, so bandwidth is never spent on results rejected from
metadata alone.

The manager performs no reasoning and keeps no state of its own — the research
state owns the visited-URL history (single source of truth) and passes it in
per call.
"""
from __future__ import annotations

from research_engine.domain.models import RawDocument, SearchCandidate, SearchTask
from research_engine.logging_setup import get_logger
from research_engine.providers.base import SearchProvider

_log = get_logger("collection.retrieval")


class RetrievalManager:
    """Retrieves search candidates per search task and downloads accepted ones."""

    def __init__(self, provider: SearchProvider, candidates_per_query: int) -> None:
        self._provider = provider
        self._candidates_per_query = max(1, candidates_per_query)

    def search(
        self,
        task: SearchTask,
        exclude_urls: frozenset[str],
        collect_task_id: str = "",
    ) -> list[SearchCandidate]:
        """Return new candidates for ``task``, attributed to its subquestion.

        Candidates whose URL the session has already seen (``exclude_urls``,
        owned by the research state) are dropped so iterations never
        re-acquire known material. A provider failure is logged and returns an
        empty list — one bad search never aborts an iteration.
        """
        try:
            candidates = self._provider.search_candidates(
                task.query, self._candidates_per_query
            )
        except Exception as exc:  # isolate a failing query
            _log.warning("Search failed for %r: %s", task.query, exc)
            return []
        fresh: list[SearchCandidate] = []
        seen: set[str] = set()
        for candidate in candidates:
            key = candidate.url or candidate.id
            if key in exclude_urls or key in seen:
                continue
            seen.add(key)
            candidate.subquestion_id = task.subquestion_id
            candidate.task_id = collect_task_id or task.id
            fresh.append(candidate)
        return fresh

    def download(self, candidates: list[SearchCandidate]) -> list[RawDocument]:
        """Download the documents for accepted candidates.

        Failures are isolated per candidate: an unfetchable page is logged and
        skipped, never aborting the batch.
        """
        documents: list[RawDocument] = []
        for candidate in candidates:
            try:
                document = self._provider.fetch(candidate)
            except Exception as exc:  # keep the session resilient to a bad page
                _log.warning("Download failed for %r: %s", candidate.url, exc)
                continue
            if document is None:
                _log.debug("No content for candidate %s", candidate.id)
                continue
            documents.append(document)
        return documents
