"""DuckDuckGo web search provider.

Uses DuckDuckGo's no-key "lite" endpoint (``lite.duckduckgo.com/lite/``) via an
HTTP POST to obtain general web results, then best-effort fetches and extracts
readable text from each result page. This adds open-web breadth beyond the
encyclopedic/academic sources. It is the least structured source, so every step
degrades gracefully: a failed page fetch falls back to the result snippet, and a
failed search returns no documents.
"""
from __future__ import annotations

import html
import re
import urllib.parse

from research_engine.domain.models import RawDocument
from research_engine.logging_setup import get_logger
from research_engine.providers.base import SearchProvider
from research_engine.providers.sources import _http
from research_engine.providers.sources._common import build_document

_log = get_logger("providers.duckduckgo")

_SEARCH_URL = "https://lite.duckduckgo.com/lite/"

# Lite result markup: <a href="URL" class='result-link'>TITLE</a>
_RESULT_RE = re.compile(
    r'<a[^>]+href="([^"]+)"[^>]*class=[\'"]result-link[\'"][^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
# Snippet cell: <td class='result-snippet'> ... </td>
_SNIPPET_RE = re.compile(
    r'<td[^>]+class=[\'"]result-snippet[\'"][^>]*>(.*?)</td>',
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")


class DuckDuckGoSearchProvider(SearchProvider):
    """Search the open web via DuckDuckGo and extract page text."""

    name = "duckduckgo"

    def __init__(
        self,
        post_text=None,
        get_text=None,
        fetch_pages: bool = True,
        max_chars: int = 4000,
    ) -> None:
        self._post_text = post_text or _http.post_text
        self._get_text = get_text or _http.get_text
        self._fetch_pages = fetch_pages
        self._max_chars = max_chars

    def search(self, query: str, limit: int) -> list[RawDocument]:
        limit = max(1, limit)
        try:
            page = self._post_text(_SEARCH_URL, {"q": query})
        except _http.SourceFetchError as exc:
            _log.warning("DuckDuckGo search failed for %r: %s", query, exc)
            return []

        results = _parse_results(page)[:limit]
        documents: list[RawDocument] = []
        for url, title, snippet in results:
            content = self._page_content(url) or snippet
            if not content:
                continue
            documents.append(
                build_document(
                    query, title or url, _http.truncate(content, self._max_chars),
                    url, self.name,
                )
            )
        return documents

    def _page_content(self, url: str) -> str:
        if not self._fetch_pages:
            return ""
        try:
            raw = self._get_text(url)
        except _http.SourceFetchError:
            return ""  # fall back to the snippet
        return _http.html_to_text(raw)


def _parse_results(page: str) -> list[tuple[str, str, str]]:
    """Extract (url, title, snippet) tuples from a DuckDuckGo lite result page."""
    snippets = [_clean(s) for s in _SNIPPET_RE.findall(page)]
    results: list[tuple[str, str, str]] = []
    for index, (href, title_html) in enumerate(_RESULT_RE.findall(page)):
        url = _resolve_url(href)
        if not url:
            continue
        snippet = snippets[index] if index < len(snippets) else ""
        results.append((url, _clean(title_html), snippet))
    return results


def _resolve_url(href: str) -> str:
    """Resolve a (possibly redirect-wrapped) DuckDuckGo link to its target URL."""
    href = html.unescape(href)
    if href.startswith("//"):
        href = "https:" + href
    parsed = urllib.parse.urlparse(href)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        target = urllib.parse.parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            return urllib.parse.unquote(target)
    return href if href.startswith("http") else ""


def _clean(fragment: str) -> str:
    return html.unescape(_TAG_RE.sub("", fragment)).strip()
