"""Shared helpers for building candidates and documents in source providers."""
from __future__ import annotations

from research_engine.domain.models import RawDocument, SearchCandidate, Source
from research_engine.utils import slugify, utc_now_iso


def candidate_key(url: str, title: str) -> str:
    """Stable id fragment derived from a result's URL (or title as fallback).

    Deriving the key from the URL means the same page found under different
    subquestions yields the same candidate/source/document ids, so downstream
    de-duplication and provenance stay consistent.
    """
    return slugify(url)[:80] or slugify(title)[:80] or "result"


def build_candidate(
    query: str,
    title: str,
    snippet: str,
    url: str,
    provider: str,
    ref: str = "",
) -> SearchCandidate:
    """Construct a :class:`SearchCandidate` with a stable, URL-derived id."""
    key = candidate_key(url, title)
    return SearchCandidate(
        id=f"cand-{key}",
        query=query,
        title=title or url,
        snippet=snippet,
        url=url,
        provider=provider,
        ref=ref or url,
    )


def build_document(candidate: SearchCandidate, content: str) -> RawDocument:
    """Construct a :class:`RawDocument` for a fetched candidate.

    The document inherits the candidate's provenance (query, subquestion/task,
    relevance score) so the chain claim → evidence → document → source stays
    intact.
    """
    key = candidate_key(candidate.url, candidate.title)
    source = Source(
        id=f"src-{key}",
        title=candidate.title,
        provider=candidate.provider,
        locator=candidate.url,
        retrieved_at=utc_now_iso(),
        domain=candidate.domain,
        authority=candidate.authority,
        authority_tier=candidate.authority_tier,
    )
    return RawDocument(
        id=f"doc-{key}",
        query=candidate.query,
        task_id=candidate.task_id,
        title=candidate.title,
        content=content,
        source=source,
        subquestion_id=candidate.subquestion_id,
        relevance_score=candidate.relevance_score,
    )
