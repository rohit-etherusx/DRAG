"""Provider interfaces.

These abstractions are the extension seam called out in ``ARCHITECTURE.md``:
new data sources and language-model backends are added by implementing these
interfaces, without touching the core engine.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from research_engine.domain.models import RawDocument


class SearchProvider(ABC):
    """Acquires raw information for a query.

    Implementations may hit a search API, read local files, call an LLM, etc.
    They are responsible only for *acquiring* information — never for reasoning.
    """

    #: Human-readable provider name, recorded on every source for provenance.
    name: str = "search"

    @abstractmethod
    def search(self, query: str, limit: int) -> list[RawDocument]:
        """Return up to ``limit`` raw documents relevant to ``query``."""
        raise NotImplementedError


class LLMProvider(ABC):
    """Optional language-model backend used for narrative synthesis."""

    #: Human-readable provider name.
    name: str = "llm"

    @property
    @abstractmethod
    def available(self) -> bool:
        """Whether the provider can currently serve requests."""
        raise NotImplementedError

    @abstractmethod
    def generate(self, prompt: str, system: str | None = None) -> str | None:
        """Return generated text, or ``None`` if generation is unavailable.

        Returning ``None`` (rather than raising) lets callers fall back to a
        deterministic path cleanly.
        """
        raise NotImplementedError
