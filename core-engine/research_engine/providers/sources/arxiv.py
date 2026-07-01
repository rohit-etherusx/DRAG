"""arXiv search provider.

Queries the arXiv Atom API (no key required) and returns each matching paper's
title and abstract as a document. Adds peer-reviewed / preprint scientific
perspective that complements the encyclopedic Wikipedia source.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from research_engine.domain.models import RawDocument
from research_engine.logging_setup import get_logger
from research_engine.providers.base import SearchProvider
from research_engine.providers.sources import _http
from research_engine.providers.sources._common import build_document

_log = get_logger("providers.arxiv")

_API = "http://export.arxiv.org/api/query"
_ATOM = "{http://www.w3.org/2005/Atom}"


class ArxivSearchProvider(SearchProvider):
    """Search arXiv and return paper abstracts."""

    name = "arxiv"

    def __init__(self, get_text=None, max_chars: int = 3000) -> None:
        self._get_text = get_text or _http.get_text
        self._max_chars = max_chars

    def search(self, query: str, limit: int) -> list[RawDocument]:
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

        documents: list[RawDocument] = []
        for entry in root.findall(f"{_ATOM}entry"):
            title = _text(entry.find(f"{_ATOM}title"))
            summary = _text(entry.find(f"{_ATOM}summary"))
            url = _text(entry.find(f"{_ATOM}id"))
            if not summary or not url:
                continue
            content = _http.truncate(f"{title}. {summary}".strip(), self._max_chars)
            documents.append(build_document(query, title or url, content, url, self.name))
        return documents


def _text(element) -> str:
    if element is None or element.text is None:
        return ""
    return " ".join(element.text.split())
