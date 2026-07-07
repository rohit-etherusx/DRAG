"""Minimal HTTP + HTML helpers for the source providers.

Uses only the standard library (``urllib``) so the engine keeps a small
dependency surface. Every network call is bounded by a timeout and carries a
descriptive ``User-Agent`` (some sources, e.g. Wikipedia, require one).

Functions raise :class:`SourceFetchError` on any failure so callers can treat
network problems uniformly (providers degrade to an empty result rather than
crashing the run).

**Concurrency safety (v0.6, T90).** Once acquisition runs on a thread pool
(``concurrency.parallel_map``) many downloads hit the *same host* at once, which
provokes rate-limit responses (Wikipedia 429s in particular). This module makes
raising ``max_workers`` safe with two Layer-7 mechanisms, both centralized here
so every source provider inherits them without interface changes:

* **Per-host concurrency cap.** A process-global registry of bounded semaphores,
  one per host, limits simultaneous requests to any single host regardless of
  how many worker threads are running. This is an explicit, inspectable limiter
  (not a hidden cache) — the only shared mutable state, and it holds no research
  knowledge.
* **Retry with backoff.** Retryable failures (HTTP 429/5xx and transient
  network errors) are retried with exponential backoff, honouring a server's
  ``Retry-After`` header when present. Non-retryable failures (4xx other than
  429, malformed URLs) fail fast, unchanged.

Neither mechanism affects *results* — only timing — and the offline provider
never imports this module, so offline runs stay byte-for-byte reproducible.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

DEFAULT_TIMEOUT = 12.0
# Browser-compatible but self-identifying: some endpoints (e.g. DuckDuckGo)
# reject unknown agents, while others (e.g. Wikipedia) require a descriptive one.
USER_AGENT = "Mozilla/5.0 (compatible; research-engine/0.2; +https://github.com)"

# --- Retry / rate-limit safety (T90) --------------------------------------
#: Default retries per request on a *retryable* failure (total attempts =
#: retries + 1). Overridable at startup via :func:`configure_http`.
DEFAULT_MAX_RETRIES = 3
#: Default cap on simultaneous in-flight requests to any single host.
DEFAULT_MAX_PER_HOST = 4
#: HTTP status codes worth retrying: rate-limiting and transient server errors.
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
#: Exponential-backoff base and ceiling (seconds).
_BACKOFF_BASE = 0.5
_BACKOFF_CAP = 8.0

# Active tunables (mutated only by configure_http, before any request runs).
_max_retries = DEFAULT_MAX_RETRIES
_max_per_host = DEFAULT_MAX_PER_HOST

# Per-host limiter: a lazily-built semaphore per host, guarded by a lock. Shared
# across all worker threads — this is the process-global concurrency budget.
_host_guard = threading.Lock()
_host_semaphores: dict[str, threading.BoundedSemaphore] = {}

# Indirection seams so tests can substitute the network and the clock without
# real sockets or real waiting. Production code uses the stdlib defaults.
_urlopen = urllib.request.urlopen
_sleep = time.sleep


class SourceFetchError(Exception):
    """Raised when an HTTP fetch or parse fails."""


def configure_http(
    *, max_retries: int | None = None, max_per_host: int | None = None
) -> None:
    """Set the HTTP retry budget and per-host concurrency cap for the process.

    Called once at startup (from the provider factory) so the values track
    :class:`~research_engine.config.EngineConfig`. Must be called before any
    fetch — it takes effect for hosts whose semaphore has not yet been created,
    which is all of them at startup. ``None`` leaves a setting unchanged.
    """
    global _max_retries, _max_per_host
    if max_retries is not None:
        _max_retries = max(0, int(max_retries))
    if max_per_host is not None:
        _max_per_host = max(1, int(max_per_host))


def _host_semaphore(host: str) -> threading.BoundedSemaphore:
    """Return the shared concurrency limiter for ``host`` (created on first use)."""
    with _host_guard:
        sem = _host_semaphores.get(host)
        if sem is None:
            sem = threading.BoundedSemaphore(_max_per_host)
            _host_semaphores[host] = sem
        return sem


def _retry_after(exc: urllib.error.HTTPError) -> float | None:
    """Seconds to wait per a server ``Retry-After`` header, if it gives one.

    Only the numeric (delta-seconds) form is honoured; the HTTP-date form falls
    back to normal backoff by returning ``None``.
    """
    headers = getattr(exc, "headers", None)
    value = headers.get("Retry-After") if headers is not None else None
    if not value:
        return None
    try:
        return min(_BACKOFF_CAP, max(0.0, float(value)))
    except (TypeError, ValueError):
        return None


def _backoff(attempt: int) -> float:
    """Exponential backoff (capped) for a zero-based retry attempt number."""
    return min(_BACKOFF_CAP, _BACKOFF_BASE * (2 ** attempt))


def _perform(
    request: urllib.request.Request, timeout: float, max_bytes: int
) -> tuple[bytes, str]:
    """Execute ``request`` under the per-host cap, retrying retryable failures.

    Returns ``(raw_bytes, charset)``. Raises :class:`SourceFetchError` on a
    non-retryable failure or once the retry budget is exhausted.
    """
    host = urllib.parse.urlparse(request.full_url).netloc
    with _host_semaphore(host):
        for attempt in range(_max_retries + 1):
            try:
                with _urlopen(request, timeout=timeout) as response:
                    raw = response.read(max_bytes)
                    charset = response.headers.get_content_charset() or "utf-8"
                return raw, charset
            except urllib.error.HTTPError as exc:
                # 429/5xx are worth retrying; other 4xx are terminal client errors.
                if exc.code in _RETRYABLE_STATUS and attempt < _max_retries:
                    wait = _retry_after(exc)
                    _sleep(wait if wait is not None else _backoff(attempt))
                    continue
                raise SourceFetchError(
                    f"{request.full_url} failed: HTTP {exc.code} {exc.reason}"
                ) from exc
            except (urllib.error.URLError, OSError) as exc:
                # Transient network/timeout errors — retry until the budget runs out.
                if attempt < _max_retries:
                    _sleep(_backoff(attempt))
                    continue
                raise SourceFetchError(
                    f"{request.full_url} failed: {exc}"
                ) from exc
            except ValueError as exc:
                # Malformed URL / unsupported scheme: not transient, do not retry.
                raise SourceFetchError(f"{request.full_url} failed: {exc}") from exc
    # Unreachable: the loop either returns or raises on every path.
    raise SourceFetchError(f"{request.full_url} failed: retries exhausted")


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
    unexpectedly large pages. Retries and the per-host concurrency cap are
    applied transparently (see the module docstring).
    """
    full_url = _build_url(url, params)
    request = urllib.request.Request(full_url, headers={"User-Agent": USER_AGENT})
    raw, charset = _perform(request, timeout, max_bytes)
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
    raw, charset = _perform(request, timeout, max_bytes)
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
