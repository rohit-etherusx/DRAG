"""Offline, deterministic providers.

These are the zero-dependency defaults that let the engine run and be tested
anywhere, reproducibly. The search provider is a *local knowledge source*
(explicitly a valid source type in ``ARCHITECTURE.md``) that synthesizes
structured notes from the query. It implements the same two-phase
candidate/fetch interface as the live sources — candidates carry a title and
snippet, and ``fetch`` synthesizes the full note — so the whole pipeline,
including candidate evaluation, is exercised offline. It is a placeholder for
real web/API providers and is honestly attributed as such in every report.
"""
from __future__ import annotations

from research_engine.domain.models import RawDocument, SearchCandidate, Source
from research_engine.providers.base import LLMProvider, SearchProvider
from research_engine.utils import keywords, utc_now_iso

# Facet templates used to give each generated document a distinct angle, so
# that downstream processing sees varied claims and entities. Each template
# deliberately mixes claim types (definitions, dates, numbers, limitations)
# so the offline path exercises typed claim extraction.
_FACETS = [
    (
        "Definition and scope",
        "{topic} is defined as a distinct area of study and practice. "
        "{Kw0} and {Kw1} are commonly identified as central to {topic}. "
        "Understanding {topic} begins with delineating its scope and core terms.",
    ),
    (
        "Historical development",
        "The development of {topic} has proceeded through several phases since 1990. "
        "Early work established {Kw0}, while later contributions emphasized {Kw1}. "
        "This trajectory shapes how {topic} is understood today.",
    ),
    (
        "Key components",
        "Analyses of {topic} frequently decompose it into 3 interacting components. "
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
        "A known limitation is that tensions between {Kw0} and {Kw1} are not fully resolved. "
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

    def search_candidates(self, query: str, limit: int) -> list[SearchCandidate]:
        topic = _display_topic(query)
        candidates: list[SearchCandidate] = []
        for index in range(max(0, limit)):
            facet_title, _template = _FACETS[index % len(_FACETS)]
            content = self._content(query, index)
            snippet = content.split(". ")[0] + "."
            slug = query_slug(query)
            candidates.append(
                SearchCandidate(
                    id=f"cand-{slug}-{index}",
                    query=query,
                    title=f"{facet_title}: {topic}",
                    snippet=snippet,
                    url=f"local://{slug}/{index}",
                    provider=self.name,
                    ref=str(index),
                )
            )
        return candidates

    def fetch(self, candidate: SearchCandidate) -> RawDocument | None:
        index = int(candidate.ref or 0)
        slug = query_slug(candidate.query)
        source = Source(
            id=f"src-{slug}-{index}",
            title=candidate.title,
            provider=self.name,
            locator=candidate.url,
            retrieved_at=utc_now_iso(),
            domain=candidate.domain,
            authority=candidate.authority,
            authority_tier=candidate.authority_tier,
        )
        return RawDocument(
            id=f"doc-{slug}-{index}",
            query=candidate.query,
            task_id=candidate.task_id,
            title=candidate.title,
            content=self._content(candidate.query, index),
            source=source,
            subquestion_id=candidate.subquestion_id,
            relevance_score=candidate.relevance_score,
        )

    def _content(self, query: str, index: int) -> str:
        """Deterministic synthetic note for ``query``'s ``index``-th facet."""
        kws = keywords(query, limit=6) or [query.strip() or "the subject"]
        kw0 = kws[0]
        kw1 = kws[1] if len(kws) > 1 else kws[0]
        _title, template = _FACETS[index % len(_FACETS)]
        return template.format(
            topic=_display_topic(query),
            Kw0=_titlecase(kw0),
            Kw1=_titlecase(kw1),
        )


class NullLLMProvider(LLMProvider):
    """LLM provider that is always unavailable.

    Used when no live model is configured; callers fall back to deterministic
    templated synthesis.
    """

    name = "none"

    @property
    def available(self) -> bool:
        return False

    def generate(
        self, prompt: str, system: str | None = None, *, json_object: bool = False
    ) -> str | None:
        return None


def _titlecase(word: str) -> str:
    return word[:1].upper() + word[1:] if word else word


def _display_topic(query: str) -> str:
    # Strip a leading facet phrase like "What is the definition of " or
    # "Current state and developments in " to recover the underlying subject by
    # taking the text after the last angle marker.
    best_idx = -1
    best_end = 0
    for marker in (" of ", " in "):
        idx = query.rfind(marker)
        if idx > best_idx:
            best_idx = idx
            best_end = idx + len(marker)
    if best_idx != -1:
        candidate = query[best_end:].strip().rstrip("?")
        if candidate:
            return candidate
    return query.strip().rstrip("?") or "the subject"


def query_slug(query: str) -> str:
    from research_engine.utils import slugify

    return slugify(query)[:48]
