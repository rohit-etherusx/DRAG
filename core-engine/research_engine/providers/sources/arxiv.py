"""arXiv search provider.

Queries the arXiv Atom API (no key required). The feed already contains each
paper's abstract, so ``search_candidates`` exposes a short snippet for
evaluation and caches the full abstract; ``fetch`` serves the cached content
without a second network call. Adds peer-reviewed / preprint scientific
perspective that complements the encyclopedic Wikipedia source.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from research_engine.domain.models import RawDocument, SearchCandidate
from research_engine.logging_setup import get_logger
from research_engine.providers.base import SearchProvider
from research_engine.providers.sources import _http
from research_engine.providers.sources._common import build_candidate, build_document

_log = get_logger("providers.arxiv")

_API = "http://export.arxiv.org/api/query"
_ATOM = "{http://www.w3.org/2005/Atom}"
_SNIPPET_CHARS = 300


class ArxivSearchProvider(SearchProvider):
    """Search arXiv and return paper abstracts."""

    name = "arxiv"

    def __init__(self, get_text=None, max_chars: int = 3000) -> None:
        self._get_text = get_text or _http.get_text
        self._max_chars = max_chars
        #: Full abstract text cached at search time, keyed by candidate url.
        self._content_by_url: dict[str, str] = {}

    def search_candidates(self, query: str, limit: int) -> list[SearchCandidate]:
        limit = max(1, limit)
        try:
            xml = self._get_text(
                _API,
                {
                    "search_query": f"all:{query}",
                    "start": "0",
                    "max_results": str(limit),
                },
            )
        except _http.SourceFetchError as exc:
            _log.warning("arXiv fetch failed for %r: %s", query, exc)
            return []

        try:
            root = ET.fromstring(xml)
        except ET.ParseError as exc:
            _log.warning("arXiv returned unparseable XML for %r: %s", query, exc)
            return []

        candidates: list[SearchCandidate] = []
        for entry in root.findall(f"{_ATOM}entry"):
            title = _text(entry.find(f"{_ATOM}title"))
            summary = _text(entry.find(f"{_ATOM}summary"))
            url = _text(entry.find(f"{_ATOM}id"))
            if not summary or not url:
                continue
            content = _http.truncate(f"{title}. {summary}".strip(), self._max_chars)
            self._content_by_url[url] = content
            snippet = _http.truncate(summary, _SNIPPET_CHARS)
            candidates.append(build_candidate(query, title or url, snippet, url, self.name))
        return candidates

    def fetch(self, candidate: SearchCandidate) -> RawDocument | None:
        content = self._content_by_url.get(candidate.url)
        if not content:
            # Cache miss (e.g. candidate persisted across provider instances):
            # the abstract is all arXiv's API offers, so nothing to download.
            _log.warning("arXiv has no cached abstract for %r", candidate.url)
            return None
        return build_document(candidate, content)


def _text(element) -> str:
    if element is None or element.text is None:
        return ""
    return " ".join(element.text.split())
