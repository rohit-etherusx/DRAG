"""Composite search provider.

Fans a query out across several underlying :class:`SearchProvider` instances
and merges their candidates, de-duplicated by URL. This is how the engine draws
evidence from *multiple independent sources* for a single subquestion. Fetches
are routed back to the provider that produced the candidate.

Each underlying provider is isolated: if one raises, it is logged and skipped
so a single failing source never breaks retrieval.
"""
from __future__ import annotations

from research_engine.domain.models import RawDocument, SearchCandidate
from research_engine.logging_setup import get_logger
from research_engine.providers.base import SearchProvider

_log = get_logger("providers.composite")


class CompositeSearchProvider(SearchProvider):
    """Aggregates candidates from multiple search providers."""

    def __init__(self, providers: list[SearchProvider], name: str | None = None) -> None:
        if not providers:
            raise ValueError("CompositeSearchProvider requires at least one provider")
        self._providers = providers
        self._by_name = {p.name: p for p in providers}
        self.name = name or "web (" + "+".join(p.name for p in providers) + ")"

    def search_candidates(self, query: str, limit: int) -> list[SearchCandidate]:
        limit = max(1, limit)
        n = len(self._providers)
        # Ask each provider for a share of the budget (at least one) so every
        # source is represented; bound the merged total for cost control.
        per_provider = max(1, round(limit / n))
        total_cap = max(limit, n)

        merged: list[SearchCandidate] = []
        seen: set[str] = set()
        for provider in self._providers:
            try:
                candidates = provider.search_candidates(query, per_provider)
            except Exception as exc:  # isolate a failing source
                _log.warning("Source %s failed for %r: %s", provider.name, query, exc)
                continue
            for candidate in candidates:
                key = candidate.url or candidate.id
                if key in seen:
                    continue
                seen.add(key)
                merged.append(candidate)
                if len(merged) >= total_cap:
                    return merged
        return merged

    def fetch(self, candidate: SearchCandidate) -> RawDocument | None:
        provider = self._by_name.get(candidate.provider)
        if provider is None:
            _log.warning(
                "No provider %r to fetch candidate %s", candidate.provider, candidate.id
            )
            return None
        try:
            return provider.fetch(candidate)
        except Exception as exc:  # isolate a failing source
            _log.warning("Fetch via %s failed for %r: %s", provider.name, candidate.url, exc)
            return None
