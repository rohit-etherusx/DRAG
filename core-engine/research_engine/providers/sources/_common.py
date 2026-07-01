"""Shared helpers for building documents from source providers."""
from __future__ import annotations

from research_engine.domain.models import RawDocument, Source
from research_engine.utils import slugify, utc_now_iso


def build_document(
    query: str, title: str, content: str, url: str, provider: str
) -> RawDocument:
    """Construct a :class:`RawDocument` with a stable, URL-derived id.

    Deriving the id from the URL means the same page collected under different
    research angles yields the same source id, so downstream de-duplication and
    provenance stay consistent.
    """
    key = slugify(url)[:80] or slugify(title)[:80] or "doc"
    source = Source(
        id=f"src-{key}",
        title=title or url,
        provider=provider,
        locator=url,
        retrieved_at=utc_now_iso(),
    )
    return RawDocument(
        id=f"doc-{key}",
        query=query,
        task_id="",  # assigned by the collector
        title=title or url,
        content=content,
        source=source,
    )
