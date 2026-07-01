"""Minimal HTTP + HTML helpers for the source providers.

Uses only the standard library (``urllib``) so the engine keeps a small
dependency surface. Every network call is bounded by a timeout and carries a
descriptive ``User-Agent`` (some sources, e.g. Wikipedia, require one).

Functions raise :class:`SourceFetchError` on any failure so callers can treat
network problems uniformly (providers degrade to an empty result rather than
crashing the run).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

DEFAULT_TIMEOUT = 12.0
# Browser-compatible but self-identifying: some endpoints (e.g. DuckDuckGo)
# reject unknown agents, while others (e.g. Wikipedia) require a descriptive one.
USER_AGENT = "Mozilla/5.0 (compatible; research-engine/0.2; +https://github.com)"


class SourceFetchError(Exception):
    """Raised when an HTTP fetch or parse fails."""


def _build_url(url: str, params: dict[str, str] | None) -> str:
    if not params:
        return url
    query = urllib.parse.urlencode(params)
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{query}"


def get_text(
    url: str,
    params: dict[str, str] | None = None,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = 2_000_000,
) -> str:
    """GET ``url`` and return the decoded body text.

    ``max_bytes`` bounds how much of the response is read, protecting against
    unexpectedly large pages.
    """
    full_url = _build_url(url, params)
    request = urllib.request.Request(full_url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(max_bytes)
            charset = response.headers.get_content_charset() or "utf-8"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise SourceFetchError(f"GET {full_url} failed: {exc}") from exc
    return raw.decode(charset, errors="replace")


def post_text(
    url: str,
    data: dict[str, str],
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = 2_000_000,
) -> str:
    """POST form-encoded ``data`` to ``url`` and return the decoded body text."""
    body = urllib.parse.urlencode(data).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(max_bytes)
            charset = response.headers.get_content_charset() or "utf-8"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise SourceFetchError(f"POST {url} failed: {exc}") from exc
    return raw.decode(charset, errors="replace")


def get_json(
    url: str,
    params: dict[str, str] | None = None,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict:
    """GET ``url`` and parse the response body as JSON."""
    text = get_text(url, params, timeout=timeout)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SourceFetchError(f"invalid JSON from {url}: {exc}") from exc


class _TextExtractor(HTMLParser):
    """Collects human-readable text, skipping script/style/head content."""

    _SKIP = {"script", "style", "head", "noscript", "template", "svg"}
    _BLOCK = {"p", "div", "section", "article", "li", "br", "h1", "h2", "h3", "tr"}

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in self._BLOCK:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in self._BLOCK:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(data)

    def text(self) -> str:
        joined = "".join(self._parts)
        # Collapse runs of whitespace within lines, keep paragraph breaks.
        lines = [" ".join(line.split()) for line in joined.splitlines()]
        return "\n".join(line for line in lines if line).strip()


def html_to_text(html: str) -> str:
    """Extract readable plain text from an HTML document (best-effort)."""
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:  # pragma: no cover - HTMLParser is lenient; guard anyway
        return ""
    return parser.text()


def truncate(text: str, max_chars: int) -> str:
    """Trim ``text`` to ``max_chars`` on a word boundary where possible."""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    clipped = text[:max_chars]
    cut = clipped.rfind(" ")
    if cut > max_chars * 0.6:
        clipped = clipped[:cut]
    return clipped.rstrip() + " …"
