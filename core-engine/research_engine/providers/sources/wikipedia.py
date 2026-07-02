"""Wikipedia search provider.

Uses the MediaWiki API (no key required) in two phases: a full-text search
returns candidates (title + search snippet + page id) without downloading any
article; ``fetch`` retrieves the plain-text extract of one accepted page.
Returns clean, structured content — no HTML parsing needed — making Wikipedia
the most reliable of the no-key sources.
"""
from __future__ import annotations

import re

from research_engine.domain.models import RawDocument, SearchCandidate
from research_engine.logging_setup import get_logger
from research_engine.providers.base import SearchProvider
from research_engine.providers.sources import _http
from research_engine.providers.sources._common import build_candidate, build_document

_log = get_logger("providers.wikipedia")

_API = "https://en.wikipedia.org/w/api.php"
_TAG_RE = re.compile(r"<[^>]+>")


class WikipediaSearchProvider(SearchProvider):
    """Search Wikipedia; download article extracts only for accepted pages."""

    name = "wikipedia"

    def __init__(self, get_json=None, max_chars: int = 4000) -> None:
        self._get_json = get_json or _http.get_json
        self._max_chars = max_chars

    def search_candidates(self, query: str, limit: int) -> list[SearchCandidate]:
        limit = max(1, limit)
        try:
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
        except _http.SourceFetchError as exc:
            _log.warning("Wikipedia search failed for %r: %s", query, exc)
            return []

        candidates: list[SearchCandidate] = []
        for hit in data.get("query", {}).get("search", []):
            title = str(hit.get("title", "")).strip()
            pageid = hit.get("pageid")
            if not title or pageid is None:
                continue
            snippet = _TAG_RE.sub("", str(hit.get("snippet", ""))).strip()
            url = "https://en.wikipedia.org/wiki/" + title.replace(" ", "_")
            candidates.append(
                build_candidate(query, title, snippet, url, self.name, ref=str(pageid))
            )
        return candidates

    def fetch(self, candidate: SearchCandidate) -> RawDocument | None:
        try:
            data = self._get_json(
                _API,
                {
                    "action": "query",
                    "prop": "extracts",
                    "explaintext": "1",
                    "exsectionformat": "plain",
                    "pageids": candidate.ref,
                    "format": "json",
                },
            )
        except _http.SourceFetchError as exc:
            _log.warning("Wikipedia fetch failed for %r: %s", candidate.title, exc)
            return None
        page = data.get("query", {}).get("pages", {}).get(str(candidate.ref), {})
        content = _http.truncate(str(page.get("extract", "")).strip(), self._max_chars)
        if not content:
            return None
        return build_document(candidate, content)
