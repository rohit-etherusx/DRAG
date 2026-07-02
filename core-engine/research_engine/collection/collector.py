"""Retrieval manager.

Executes targeted retrieval for the research plan (``OBJECTIVE.md`` module 2):
every subquestion's search queries run independently and their candidates are
merged and de-duplicated, increasing recall while keeping results attributable
to the subquestion they serve. Downloading is a separate step that operates
only on candidates accepted by the evaluation gate, so bandwidth is never
spent on results that were rejected from metadata alone.

The manager performs no reasoning — only acquisition.
"""
from __future__ import annotations

from research_engine.domain.models import RawDocument, SearchCandidate, SubQuestion, Task
from research_engine.logging_setup import get_logger
from research_engine.providers.base import SearchProvider

_log = get_logger("collection.retrieval")


class RetrievalManager:
    """Retrieves search candidates per subquestion and downloads accepted ones."""

    def __init__(self, provider: SearchProvider, candidates_per_query: int) -> None:
        self._provider = provider
        self._candidates_per_query = max(1, candidates_per_query)
        #: URLs already returned this session (cross-subquestion de-duplication).
        self._seen_urls: set[str] = set()

    def retrieve(
        self,
        subquestion: SubQuestion,
        task: Task,
        queries: list[str] | None = None,
    ) -> list[SearchCandidate]:
        """Return merged, de-duplicated candidates for ``subquestion``.

        Each search query runs independently; a query failure is logged and
        skipped so one bad query never empties a subquestion. ``queries``
        overrides the subquestion's own queries (used by the research loop for
        follow-up searches). Candidates already retrieved this session (same
        URL) are dropped so iterations don't re-download known material.
        """
        merged: list[SearchCandidate] = []
        for query in queries or subquestion.search_queries or [subquestion.question]:
            try:
                candidates = self._provider.search_candidates(
                    query, self._candidates_per_query
                )
            except Exception as exc:  # isolate a failing query
                _log.warning("Search failed for %r: %s", query, exc)
                continue
            for candidate in candidates:
                key = candidate.url or candidate.id
                if key in self._seen_urls:
                    continue
                self._seen_urls.add(key)
                candidate.subquestion_id = subquestion.id
                candidate.task_id = task.id
                merged.append(candidate)
        return merged

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
