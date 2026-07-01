"""Offline, deterministic providers.

These are the zero-dependency defaults that let the engine run and be tested
anywhere, reproducibly. The search provider is a *local knowledge source*
(explicitly a valid source type in ``ARCHITECTURE.md``) that synthesizes
structured notes from the query. It is a placeholder for real web/API providers
and is honestly attributed as such in every report.
"""
from __future__ import annotations

from research_engine.domain.models import RawDocument, Source
from research_engine.providers.base import LLMProvider, SearchProvider
from research_engine.utils import keywords, utc_now_iso

# Angle templates used to give each generated document a distinct facet, so that
# downstream processing sees varied claims and entities rather than repetition.
_FACETS = [
    (
        "Definition and scope",
        "{topic} refers to a distinct area of study and practice. "
        "{Kw0} and {Kw1} are commonly identified as central to {topic}. "
        "Understanding {topic} begins with delineating its scope and core terms.",
    ),
    (
        "Historical development",
        "The development of {topic} has proceeded through several phases. "
        "Early work established {Kw0}, while later contributions emphasized {Kw1}. "
        "This trajectory shapes how {topic} is understood today.",
    ),
    (
        "Key components",
        "Analyses of {topic} frequently decompose it into interacting components. "
        "{Kw0} interacts with {Kw1} to produce the behavior characteristic of {topic}. "
        "These components are studied both independently and as a system.",
    ),
    (
        "Applications and impact",
        "{topic} has been applied across a range of contexts. "
        "Practical uses often connect {Kw0} with {Kw1}. "
        "The impact of {topic} is assessed by its effect on outcomes in those contexts.",
    ),
    (
        "Challenges and open problems",
        "Several challenges remain in the study of {topic}. "
        "Tensions between {Kw0} and {Kw1} are not fully resolved. "
        "These open problems motivate ongoing investigation into {topic}.",
    ),
    (
        "Current state and outlook",
        "The current state of {topic} reflects active development. "
        "Recent attention has focused on {Kw0}, with {Kw1} emerging as a related concern. "
        "The outlook for {topic} depends on how these threads evolve.",
    ),
]


class OfflineSearchProvider(SearchProvider):
    """Deterministic local-knowledge search provider.

    Given a query, it returns a stable set of structured notes derived from the
    query terms. Identical inputs always yield identical outputs, satisfying the
    reproducibility principle.
    """

    name = "local-knowledge (offline heuristic)"

    def search(self, query: str, limit: int) -> list[RawDocument]:
        kws = keywords(query, limit=6) or [query.strip() or "the subject"]
        kw0 = kws[0]
        kw1 = kws[1] if len(kws) > 1 else kws[0]
        topic = _display_topic(query)

        docs: list[RawDocument] = []
        for index in range(max(0, limit)):
            facet_title, template = _FACETS[index % len(_FACETS)]
            content = template.format(
                topic=topic,
                Kw0=_titlecase(kw0),
                Kw1=_titlecase(kw1),
            )
            doc_id = f"{query_slug(query)}-{index}"
            source = Source(
                id=f"src-{doc_id}",
                title=f"{facet_title}: {topic}",
                provider=self.name,
                locator=f"local://{query_slug(query)}/{index}",
                retrieved_at=utc_now_iso(),
            )
            docs.append(
                RawDocument(
                    id=f"doc-{doc_id}",
                    query=query,
                    task_id="",  # assigned by the collector
                    title=source.title,
                    content=content,
                    source=source,
                )
            )
        return docs


class NullLLMProvider(LLMProvider):
    """LLM provider that is always unavailable.

    Used when no live model is configured; callers fall back to deterministic
    templated synthesis.
    """

    name = "none"

    @property
    def available(self) -> bool:
        return False

    def generate(self, prompt: str, system: str | None = None) -> str | None:
        return None


def _titlecase(word: str) -> str:
    return word[:1].upper() + word[1:] if word else word


def _display_topic(query: str) -> str:
    # Strip a leading facet phrase like "Overview and definition of " or
    # "Current state and developments in " to recover the underlying topic by
    # taking the text after the last angle marker.
    best_idx = -1
    best_end = 0
    for marker in (" of ", " in "):
        idx = query.rfind(marker)
        if idx > best_idx:
            best_idx = idx
            best_end = idx + len(marker)
    if best_idx != -1:
        candidate = query[best_end:].strip()
        if candidate:
            return candidate
    return query.strip()


def query_slug(query: str) -> str:
    from research_engine.utils import slugify

    return slugify(query)[:48]
