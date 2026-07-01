"""Composite search provider.

Fans a query out across several underlying :class:`SearchProvider` instances and
merges their documents, de-duplicated by source locator. This is how the engine
draws evidence from *multiple independent sources* for a single research angle.

Each underlying provider is isolated: if one raises, it is logged and skipped so
a single failing source never breaks collection.
"""
from __future__ import annotations

from research_engine.domain.models import RawDocument
from research_engine.logging_setup import get_logger
from research_engine.providers.base import SearchProvider

_log = get_logger("providers.composite")


class CompositeSearchProvider(SearchProvider):
    """Aggregates results from multiple search providers."""

    def __init__(self, providers: list[SearchProvider], name: str | None = None) -> None:
        if not providers:
            raise ValueError("CompositeSearchProvider requires at least one provider")
        self._providers = providers
        self.name = name or "web (" + "+".join(p.name for p in providers) + ")"

    def search(self, query: str, limit: int) -> list[RawDocument]:
        limit = max(1, limit)
        n = len(self._providers)
        # Ask each provider for a share of the budget (at least one) so every
        # source is represented; bound the merged total for cost control.
        per_provider = max(1, round(limit / n))
        total_cap = max(limit, n)

        merged: list[RawDocument] = []
        seen: set[str] = set()
        for provider in self._providers:
            try:
                documents = provider.search(query, per_provider)
            except Exception as exc:  # isolate a failing source
                _log.warning("Source %s failed for %r: %s", provider.name, query, exc)
                continue
            for document in documents:
                locator = document.source.locator or document.id
                if locator in seen:
                    continue
                seen.add(locator)
                merged.append(document)
                if len(merged) >= total_cap:
                    return merged
        return merged
