import unittest

from tests import _path  # noqa: F401

from research_engine.domain.models import RawDocument, SearchCandidate, Source
from research_engine.providers.base import SearchProvider
from research_engine.providers.sources import _http
from research_engine.providers.sources.arxiv import ArxivSearchProvider
from research_engine.providers.sources.composite import CompositeSearchProvider
from research_engine.providers.sources.duckduckgo import DuckDuckGoSearchProvider
from research_engine.providers.sources.wikipedia import WikipediaSearchProvider


class HtmlToTextTests(unittest.TestCase):
    def test_strips_tags_and_scripts(self):
        html = (
            "<html><head><style>.x{}</style></head><body>"
            "<script>var x=1;</script><p>Hello world.</p>"
            "<div>Second line.</div></body></html>"
        )
        text = _http.html_to_text(html)
        self.assertIn("Hello world.", text)
        self.assertIn("Second line.", text)
        self.assertNotIn("var x", text)
        self.assertNotIn(".x{}", text)

    def test_truncate_adds_ellipsis(self):
        out = _http.truncate("word " * 50, 40)
        self.assertLessEqual(len(out), 44)
        self.assertTrue(out.endswith("…"))


class WikipediaProviderTests(unittest.TestCase):
    def setUp(self):
        self.fetch_calls = []

    def _fake_get_json(self, url, params=None, **kwargs):
        if params and params.get("list") == "search":
            return {
                "query": {
                    "search": [
                        {
                            "pageid": 42,
                            "title": "Quantum computing",
                            "snippet": "Computation using <b>qubits</b>.",
                        }
                    ]
                }
            }
        self.fetch_calls.append(params)
        return {
            "query": {
                "pages": {
                    "42": {
                        "title": "Quantum computing",
                        "extract": "Quantum computing uses qubits. It exploits superposition.",
                    }
                }
            }
        }

    def test_candidates_are_metadata_only(self):
        provider = WikipediaSearchProvider(get_json=self._fake_get_json)
        candidates = provider.search_candidates("quantum computing", 3)
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate.provider, "wikipedia")
        self.assertEqual(candidate.title, "Quantum computing")
        self.assertEqual(candidate.snippet, "Computation using qubits.")  # tags stripped
        self.assertTrue(candidate.url.startswith("https://en.wikipedia.org/wiki/"))
        # The article body is NOT downloaded during search.
        self.assertEqual(self.fetch_calls, [])

    def test_fetch_downloads_extract_with_provenance(self):
        provider = WikipediaSearchProvider(get_json=self._fake_get_json)
        candidate = provider.search_candidates("quantum computing", 3)[0]
        document = provider.fetch(candidate)
        self.assertIsNotNone(document)
        self.assertIn("qubits", document.content)
        self.assertEqual(document.source.provider, "wikipedia")
        self.assertEqual(document.source.locator, candidate.url)
        self.assertEqual(len(self.fetch_calls), 1)

    def test_empty_search_returns_no_candidates(self):
        provider = WikipediaSearchProvider(
            get_json=lambda url, params=None, **k: {"query": {"search": []}}
        )
        self.assertEqual(provider.search_candidates("nothing", 3), [])

    def test_search_error_is_swallowed(self):
        def boom(url, params=None, **kwargs):
            raise _http.SourceFetchError("network down")

        provider = WikipediaSearchProvider(get_json=boom)
        self.assertEqual(provider.search_candidates("x", 3), [])

    def test_fetch_error_returns_none(self):
        def boom(url, params=None, **kwargs):
            raise _http.SourceFetchError("network down")

        provider = WikipediaSearchProvider(get_json=boom)
        candidate = SearchCandidate(
            id="cand-x", query="q", title="T", snippet="", url="https://w/x",
            provider="wikipedia", ref="42",
        )
        self.assertIsNone(provider.fetch(candidate))


_ARXIV_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/1234.5678</id>
    <title>A Study of Qubits</title>
    <summary>We investigate qubit coherence in noisy systems.</summary>
  </entry>
</feed>"""


class ArxivProviderTests(unittest.TestCase):
    def test_candidates_and_cached_fetch(self):
        provider = ArxivSearchProvider(get_text=lambda url, params=None, **k: _ARXIV_XML)
        candidates = provider.search_candidates("qubits", 3)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].provider, "arxiv")
        self.assertIn("coherence", candidates[0].snippet)

        document = provider.fetch(candidates[0])
        self.assertIsNotNone(document)
        self.assertIn("coherence", document.content)
        self.assertEqual(document.source.locator, "http://arxiv.org/abs/1234.5678")

    def test_fetch_without_cache_returns_none(self):
        provider = ArxivSearchProvider(get_text=lambda url, params=None, **k: _ARXIV_XML)
        stray = SearchCandidate(
            id="cand-s", query="q", title="T", snippet="", url="http://arxiv.org/abs/0",
            provider="arxiv",
        )
        self.assertIsNone(provider.fetch(stray))

    def test_bad_xml_returns_empty(self):
        provider = ArxivSearchProvider(get_text=lambda url, params=None, **k: "<not xml")
        self.assertEqual(provider.search_candidates("x", 2), [])


# DuckDuckGo lite result markup: href before a single-quoted result-link class.
_DDG_HTML = """
<table>
  <tr><td>
    <a href="https://example.com/a" class='result-link'>First &amp; Best</a>
  </td></tr>
  <tr><td class='result-snippet'>A snippet about the topic.</td></tr>
  <tr><td>
    <a href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fb" class='result-link'>Second</a>
  </td></tr>
  <tr><td class='result-snippet'>Another snippet.</td></tr>
</table>
"""


class DuckDuckGoProviderTests(unittest.TestCase):
    def test_candidates_parse_results_without_page_fetch(self):
        def get_text(url, params=None, **kwargs):
            raise AssertionError("search_candidates must not download pages")

        provider = DuckDuckGoSearchProvider(
            post_text=lambda url, data, **k: _DDG_HTML, get_text=get_text
        )
        candidates = provider.search_candidates("topic", 5)
        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0].url, "https://example.com/a")
        self.assertEqual(candidates[0].title, "First & Best")
        self.assertEqual(candidates[0].snippet, "A snippet about the topic.")
        # Redirect link is resolved to the underlying URL.
        self.assertEqual(candidates[1].url, "https://example.org/b")

    def test_fetch_extracts_page_text(self):
        provider = DuckDuckGoSearchProvider(
            post_text=lambda url, data, **k: _DDG_HTML,
            get_text=lambda url, params=None, **k: "<p>Full page body.</p>",
        )
        candidate = provider.search_candidates("topic", 1)[0]
        document = provider.fetch(candidate)
        self.assertIn("Full page body.", document.content)

    def test_fetch_falls_back_to_snippet_when_page_fails(self):
        def get_text(url, params=None, **kwargs):
            raise _http.SourceFetchError("page down")

        provider = DuckDuckGoSearchProvider(
            post_text=lambda url, data, **k: _DDG_HTML, get_text=get_text
        )
        candidate = provider.search_candidates("topic", 1)[0]
        document = provider.fetch(candidate)
        self.assertIn("snippet", document.content)

    def test_search_error_returns_empty(self):
        def boom(url, data, **kwargs):
            raise _http.SourceFetchError("ddg down")

        provider = DuckDuckGoSearchProvider(post_text=boom)
        self.assertEqual(provider.search_candidates("topic", 3), [])


class _StubProvider(SearchProvider):
    def __init__(self, name, candidates):
        self.name = name
        self._candidates = candidates
        for c in self._candidates:
            c.provider = name

    def search_candidates(self, query, limit):
        return self._candidates[:limit]

    def fetch(self, candidate):
        return RawDocument(
            id=f"doc-{candidate.id}",
            query=candidate.query,
            task_id=candidate.task_id,
            title=candidate.title,
            content=f"content from {self.name}",
            source=Source(
                id=f"src-{candidate.id}", title=candidate.title,
                provider=self.name, locator=candidate.url,
            ),
        )


class _BoomProvider(SearchProvider):
    name = "boom"

    def search_candidates(self, query, limit):
        raise RuntimeError("kaboom")

    def fetch(self, candidate):
        raise RuntimeError("kaboom")


def _cand(url, provider="p"):
    return SearchCandidate(
        id=f"cand-{url}", query="q", title=url, snippet="s", url=url,
        provider=provider,
    )


class CompositeProviderTests(unittest.TestCase):
    def test_merges_and_deduplicates(self):
        a = _StubProvider("a", [_cand("u1"), _cand("u2")])
        b = _StubProvider("b", [_cand("u2"), _cand("u3")])  # u2 duplicates a's
        composite = CompositeSearchProvider([a, b])
        candidates = composite.search_candidates("q", 6)
        self.assertEqual(sorted(c.url for c in candidates), ["u1", "u2", "u3"])

    def test_fetch_routes_to_owning_provider(self):
        a = _StubProvider("a", [_cand("u1")])
        b = _StubProvider("b", [_cand("u2")])
        composite = CompositeSearchProvider([a, b])
        candidates = composite.search_candidates("q", 4)
        by_url = {c.url: c for c in candidates}
        self.assertEqual(
            composite.fetch(by_url["u2"]).content, "content from b"
        )

    def test_isolates_failing_provider(self):
        good = _StubProvider("good", [_cand("u1")])
        composite = CompositeSearchProvider([_BoomProvider(), good])
        candidates = composite.search_candidates("q", 3)
        self.assertEqual([c.url for c in candidates], ["u1"])

    def test_fetch_failure_returns_none(self):
        composite = CompositeSearchProvider([_BoomProvider()])
        self.assertIsNone(composite.fetch(_cand("u1", provider="boom")))
        # Unknown provider on the candidate is also handled.
        self.assertIsNone(composite.fetch(_cand("u2", provider="ghost")))

    def test_requires_at_least_one_provider(self):
        with self.assertRaises(ValueError):
            CompositeSearchProvider([])


if __name__ == "__main__":
    unittest.main()
