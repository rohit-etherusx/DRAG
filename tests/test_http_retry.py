"""Tests for the HTTP retry/backoff + per-host concurrency cap (T90).

These exercise the shared ``_http`` layer directly, substituting the network
(``_http._urlopen``) and the clock (``_http._sleep``) so no real sockets or
real waits are involved. The behaviour proven here is what makes raising
``max_workers`` safe: retryable failures are retried with backoff, terminal
failures fail fast, and no host ever sees more than the configured number of
simultaneous requests.
"""
import threading
import unittest
import urllib.error

from tests import _path  # noqa: F401

from research_engine.concurrency import parallel_map
from research_engine.providers.sources import _http


class _FakeHeaders:
    """Minimal stand-in for an HTTP headers object."""

    def __init__(self, values=None):
        self._values = values or {}

    def get(self, key, default=None):
        return self._values.get(key, default)

    def get_content_charset(self):
        return "utf-8"


class _FakeResponse:
    """Context-manager response exposing the bits ``_perform`` reads."""

    def __init__(self, body: bytes = b"ok"):
        self._body = body
        self.headers = _FakeHeaders()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, _max_bytes=None):
        return self._body


def _http_error(code: int, retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = _FakeHeaders({"Retry-After": retry_after} if retry_after else {})
    return urllib.error.HTTPError(
        "https://host/x", code, f"status {code}", headers, None
    )


class HttpRetryTests(unittest.TestCase):
    def setUp(self):
        # Preserve and restore module state so tests don't leak into each other.
        self._saved = (
            _http._urlopen,
            _http._sleep,
            _http._max_retries,
            _http._max_per_host,
            dict(_http._host_semaphores),
        )
        self._sleeps: list[float] = []
        _http._sleep = self._sleeps.append
        _http._host_semaphores = {}
        _http.configure_http(max_retries=3, max_per_host=4)

    def tearDown(self):
        (
            _http._urlopen,
            _http._sleep,
            _http._max_retries,
            _http._max_per_host,
            _http._host_semaphores,
        ) = self._saved

    def test_retries_then_succeeds_on_429(self):
        attempts = {"n": 0}

        def opener(request, timeout=None):
            attempts["n"] += 1
            if attempts["n"] <= 2:
                raise _http_error(429)
            return _FakeResponse(b"done")

        _http._urlopen = opener
        result = _http.get_text("https://host/page")
        self.assertEqual(result, "done")
        self.assertEqual(attempts["n"], 3)          # 2 failures + 1 success
        self.assertEqual(len(self._sleeps), 2)      # backoff before each retry

    def test_retry_after_header_is_honoured(self):
        state = {"first": True}

        def opener(request, timeout=None):
            if state["first"]:
                state["first"] = False
                raise _http_error(503, retry_after="2")
            return _FakeResponse(b"ok")

        _http._urlopen = opener
        _http.get_text("https://host/page")
        self.assertEqual(self._sleeps, [2.0])       # waited exactly Retry-After

    def test_non_retryable_status_fails_fast(self):
        attempts = {"n": 0}

        def opener(request, timeout=None):
            attempts["n"] += 1
            raise _http_error(404)

        _http._urlopen = opener
        with self.assertRaises(_http.SourceFetchError):
            _http.get_text("https://host/missing")
        self.assertEqual(attempts["n"], 1)          # no retries on a 4xx
        self.assertEqual(self._sleeps, [])

    def test_retry_budget_is_bounded(self):
        attempts = {"n": 0}

        def opener(request, timeout=None):
            attempts["n"] += 1
            raise _http_error(503)

        _http._urlopen = opener
        _http.configure_http(max_retries=2)
        with self.assertRaises(_http.SourceFetchError):
            _http.get_text("https://host/page")
        self.assertEqual(attempts["n"], 3)          # retries(2) + 1
        self.assertEqual(len(self._sleeps), 2)

    def test_transient_network_error_is_retried(self):
        attempts = {"n": 0}

        def opener(request, timeout=None):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise urllib.error.URLError("connection reset")
            return _FakeResponse(b"recovered")

        _http._urlopen = opener
        self.assertEqual(_http.get_text("https://host/page"), "recovered")
        self.assertEqual(attempts["n"], 2)

    def test_zero_retries_disables_retrying(self):
        attempts = {"n": 0}

        def opener(request, timeout=None):
            attempts["n"] += 1
            raise _http_error(429)

        _http._urlopen = opener
        _http.configure_http(max_retries=0)
        with self.assertRaises(_http.SourceFetchError):
            _http.get_text("https://host/page")
        self.assertEqual(attempts["n"], 1)


class HostConcurrencyCapTests(unittest.TestCase):
    def setUp(self):
        self._saved = (
            _http._urlopen,
            _http._sleep,
            _http._max_retries,
            _http._max_per_host,
            dict(_http._host_semaphores),
        )
        _http._sleep = lambda _s: None
        _http._host_semaphores = {}

    def tearDown(self):
        (
            _http._urlopen,
            _http._sleep,
            _http._max_retries,
            _http._max_per_host,
            _http._host_semaphores,
        ) = self._saved

    def test_same_host_reuses_semaphore_distinct_hosts_do_not(self):
        _http.configure_http(max_per_host=4)
        a1 = _http._host_semaphore("en.wikipedia.org")
        a2 = _http._host_semaphore("en.wikipedia.org")
        b = _http._host_semaphore("arxiv.org")
        self.assertIs(a1, a2)
        self.assertIsNot(a1, b)

    def test_no_more_than_cap_concurrent_requests_per_host(self):
        cap = 3
        _http.configure_http(max_per_host=cap)
        lock = threading.Lock()
        state = {"active": 0, "peak": 0}

        def opener(request, timeout=None):
            with lock:
                state["active"] += 1
                state["peak"] = max(state["peak"], state["active"])
            # Hold the slot briefly so overlap is possible if the cap failed.
            for _ in range(2000):
                pass
            with lock:
                state["active"] -= 1
            return _FakeResponse(b"ok")

        _http._urlopen = opener
        urls = [f"https://host/page-{i}" for i in range(24)]  # all same host
        results = parallel_map(lambda u: _http.get_text(u), urls, max_workers=12)

        self.assertEqual(len(results), 24)
        # The semaphore strictly bounds concurrency: peak can never exceed the cap.
        self.assertLessEqual(state["peak"], cap)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
