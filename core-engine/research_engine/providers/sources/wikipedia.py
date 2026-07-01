"""Wikipedia search provider.

Uses the MediaWiki API (no key required): a full-text search to find relevant
articles, then a plain-text extract of each. Returns clean, structured content —
no HTML parsing needed — making Wikipedia the most reliable of the no-key
sources.
"""
from __future__ import annotations

from research_engine.domain.models import RawDocument
from research_engine.logging_setup import get_logger
from research_engine.providers.base import SearchProvider
from research_engine.providers.sources import _http
from research_engine.providers.sources._common import build_document

_log = get_logger("providers.wikipedia")

_API = "https://en.wikipedia.org/w/api.php"


class WikipediaSearchProvider(SearchProvider):
    """Search Wikipedia and return plain-text article extracts."""

    name = "wikipedia"

    def __init__(self, get_json=None, max_chars: int = 4000) -> None:
        self._get_json = get_json or _http.get_json
        self._max_chars = max_chars

    def search(self, query: str, limit: int) -> list[RawDocument]:
        limit = max(1, limit)
        try:
            hits = self._search_titles(query, limit)
            if not hits:
                return []
            extracts = self._fetch_extracts([h["pageid"] for h in hits])
        except _http.SourceFetchError as exc:
            _log.warning("Wikipedia fetch failed for %r: %s", query, exc)
            return []

        documents: list[RawDocument] = []
        for hit in hits:
            page = extracts.get(str(hit["pageid"]))
            if not page:
                continue
            content = _http.truncate(page.get("extract", "").strip(), self._max_chars)
            if not content:
                continue
            title = page.get("title", hit.get("title", query))
            url = "https://en.wikipedia.org/wiki/" + title.replace(" ", "_")
            documents.append(build_document(query, title, content, url, self.name))
        return documents

    def _search_titles(self, query: str, limit: int) -> list[dict]:
        data = self._get_json(
            _API,
            {
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": str(limit),
                "format": "json",
            },
        )
        return data.get("query", {}).get("search", [])

    def _fetch_extracts(self, pageids: list[int]) -> dict[str, dict]:
        data = self._get_json(
            _API,
            {
                "action": "query",
                "prop": "extracts",
                "explaintext": "1",
                "exsectionformat": "plain",
                "exlimit": "max",
                "pageids": "|".join(str(pid) for pid in pageids),
                "format": "json",
            },
        )
        return data.get("query", {}).get("pages", {})
