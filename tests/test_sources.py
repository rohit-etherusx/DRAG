import unittest

from tests import _path  # noqa: F401

from research_engine.domain.models import RawDocument, Source
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
    def _fake_get_json(self, url, params=None, **kwargs):
        if params and params.get("list") == "search":
            return {"query": {"search": [{"pageid": 42, "title": "Quantum computing"}]}}
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

    def test_returns_documents_with_provenance(self):
        provider = WikipediaSearchProvider(get_json=self._fake_get_json)
        docs = provider.search("quantum computing", 3)
        self.assertEqual(len(docs), 1)
        doc = docs[0]
        self.assertEqual(doc.source.provider, "wikipedia")
        self.assertIn("qubits", doc.content)
        self.assertTrue(doc.source.locator.startswith("https://en.wikipedia.org/wiki/"))

    def test_empty_search_returns_no_documents(self):
        provider = WikipediaSearchProvider(
            get_json=lambda url, params=None, **k: {"query": {"search": []}}
        )
        self.assertEqual(provider.search("nothing", 3), [])

    def test_fetch_error_is_swallowed(self):
        def boom(url, params=None, **kwargs):
            raise _http.SourceFetchError("network down")

        provider = WikipediaSearchProvider(get_json=boom)
        self.assertEqual(provider.search("x", 3), [])


_ARXIV_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/1234.5678</id>
    <title>A Study of Qubits</title>
    <summary>We investigate qubit coherence in noisy systems.</summary>
  </entry>
</feed>"""


class ArxivProviderTests(unittest.TestCase):
    def test_parses_entries(self):
        provider = ArxivSearchProvider(get_text=lambda url, params=None, **k: _ARXIV_XML)
        docs = provider.search("qubits", 3)
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].source.provider, "arxiv")
        self.assertIn("coherence", docs[0].content)
        self.assertEqual(docs[0].source.locator, "http://arxiv.org/abs/1234.5678")

    def test_bad_xml_returns_empty(self):
        provider = ArxivSearchProvider(get_text=lambda url, params=None, **k: "<not xml")
        self.assertEqual(provider.search("x", 2), [])


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
    def test_parses_results_and_decodes_redirect(self):
        provider = DuckDuckGoSearchProvider(
            post_text=lambda url, data, **k: _DDG_HTML, fetch_pages=False
        )
        docs = provider.search("topic", 5)
        self.assertEqual(len(docs), 2)
        self.assertEqual(docs[0].source.locator, "https://example.com/a")
        self.assertEqual(docs[0].title, "First & Best")
        # Redirect link is resolved to the underlying URL.
        self.assertEqual(docs[1].source.locator, "https://example.org/b")

    def test_falls_back_to_snippet_when_page_fetch_fails(self):
        def get_text(url, params=None, **kwargs):
            raise _http.SourceFetchError("page down")

        provider = DuckDuckGoSearchProvider(
            post_text=lambda url, data, **k: _DDG_HTML,
            get_text=get_text,
            fetch_pages=True,
        )
        docs = provider.search("topic", 1)
        self.assertEqual(len(docs), 1)
        self.assertIn("snippet", docs[0].content)

    def test_search_error_returns_empty(self):
        def boom(url, data, **kwargs):
            raise _http.SourceFetchError("ddg down")

        provider = DuckDuckGoSearchProvider(post_text=boom, fetch_pages=False)
        self.assertEqual(provider.search("topic", 3), [])


class _StubProvider(SearchProvider):
    def __init__(self, name, docs):
        self.name = name
        self._docs = docs

    def search(self, query, limit):
        return self._docs[:limit]


class _BoomProvider(SearchProvider):
    name = "boom"

    def search(self, query, limit):
        raise RuntimeError("kaboom")


def _doc(locator, provider="p"):
    return RawDocument(
        id=f"doc-{locator}",
        query="q",
        task_id="",
        title=locator,
        content="content",
        source=Source(id=f"src-{locator}", title="t", provider=provider, locator=locator),
    )


class CompositeProviderTests(unittest.TestCase):
    def test_merges_and_deduplicates(self):
        a = _StubProvider("a", [_doc("u1"), _doc("u2")])
        b = _StubProvider("b", [_doc("u2"), _doc("u3")])  # u2 duplicates a's
        composite = CompositeSearchProvider([a, b])
        docs = composite.search("q", 6)
        locators = [d.source.locator for d in docs]
        self.assertEqual(sorted(locators), ["u1", "u2", "u3"])

    def test_isolates_failing_provider(self):
        good = _StubProvider("good", [_doc("u1")])
        composite = CompositeSearchProvider([_BoomProvider(), good])
        docs = composite.search("q", 3)
        self.assertEqual([d.source.locator for d in docs], ["u1"])

    def test_requires_at_least_one_provider(self):
        with self.assertRaises(ValueError):
            CompositeSearchProvider([])


if __name__ == "__main__":
    unittest.main()
