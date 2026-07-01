"""Evidence collection.

Delegates acquisition to a :class:`SearchProvider` and stamps each returned
document with the originating task. It performs no reasoning — only gathering.
"""
from __future__ import annotations

from research_engine.domain.models import RawDocument, Task
from research_engine.providers.base import SearchProvider


class EvidenceCollector:
    """Collects raw documents for a collection task via a search provider."""

    def __init__(self, provider: SearchProvider, documents_per_query: int) -> None:
        self._provider = provider
        self._documents_per_query = documents_per_query

    def collect(self, task: Task) -> list[RawDocument]:
        """Return raw documents for ``task``'s query, tagged with the task id."""
        query = task.query or task.description
        documents = self._provider.search(query, self._documents_per_query)
        for document in documents:
            document.task_id = task.id
        return documents
