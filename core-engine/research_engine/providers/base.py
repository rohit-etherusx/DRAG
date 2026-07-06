"""Provider interfaces.

These abstractions are the extension seam called out in ``ARCHITECTURE.md``:
new data sources and language-model backends are added by implementing these
interfaces, without touching the core engine.

Search is *two-phase* (v0.4): ``search_candidates`` returns lightweight result
metadata (title, snippet, URL) and ``fetch`` downloads the full content of one
candidate. Candidate evaluation runs between the two phases, so documents are
only ever downloaded for candidates that passed the relevance/authority gate —
this is what keeps irrelevant pages out of the bandwidth and token budget.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from research_engine.domain.models import RawDocument, SearchCandidate


class SearchProvider(ABC):
    """Acquires raw information for a query in two phases.

    Implementations may hit a search API, read local files, call an LLM, etc.
    They are responsible only for *acquiring* information — never for reasoning.
    """

    #: Human-readable provider name, recorded on every source for provenance.
    name: str = "search"

    @abstractmethod
    def search_candidates(self, query: str, limit: int) -> list[SearchCandidate]:
        """Return up to ``limit`` result candidates (metadata only, no download)."""
        raise NotImplementedError

    @abstractmethod
    def fetch(self, candidate: SearchCandidate) -> RawDocument | None:
        """Download the full content of an accepted candidate.

        Returns ``None`` when the content cannot be retrieved; callers treat
        that as a per-candidate failure and continue.
        """
        raise NotImplementedError


class LLMProvider(ABC):
    """Optional language-model backend used for semantic tasks only."""

    #: Human-readable provider name.
    name: str = "llm"

    @property
    @abstractmethod
    def available(self) -> bool:
        """Whether the provider can currently serve requests."""
        raise NotImplementedError

    @abstractmethod
    def generate(
        self, prompt: str, system: str | None = None, *, json_object: bool = False
    ) -> str | None:
        """Return generated text, or ``None`` if generation is unavailable.

        Returning ``None`` (rather than raising) lets callers fall back to a
        deterministic path cleanly.

        ``json_object`` asks the backend to constrain output to a single JSON
        object (via the provider's structured-output mode where supported).
        Callers that parse the response as JSON — claim extraction, the
        equivalence judge, the LLM planner — pass ``True``; prose callers leave
        it ``False``. Implementations that cannot honour it must ignore it,
        never fail.
        """
        raise NotImplementedError
