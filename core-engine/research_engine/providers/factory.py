"""Provider selection.

Chooses concrete providers from configuration, keeping construction logic out of
the orchestrator. The search provider is a composite of real no-key sources
(Wikipedia + arXiv + DuckDuckGo) by default, or the deterministic offline stub
when ``search_provider == "offline"``. The LLM provider is the configured
provider (OpenRouter by default) when available and enabled, otherwise a null
provider so the pipeline degrades cleanly to deterministic synthesis.
"""
from __future__ import annotations

from research_engine.config import EngineConfig
from research_engine.logging_setup import get_logger
from research_engine.providers.base import LLMProvider, SearchProvider
from research_engine.providers.offline import NullLLMProvider, OfflineSearchProvider
from research_engine.providers.openrouter_provider import OpenRouterProvider
from research_engine.providers.sources.arxiv import ArxivSearchProvider
from research_engine.providers.sources.composite import CompositeSearchProvider
from research_engine.providers.sources.duckduckgo import DuckDuckGoSearchProvider
from research_engine.providers.sources.wikipedia import WikipediaSearchProvider

_log = get_logger("providers.factory")


def build_search_provider(config: EngineConfig) -> SearchProvider:
    """Return the search provider for a run.

    "offline" selects the deterministic local-knowledge stub (reproducible, no
    network). Any other value ("web", the default) composes the real no-key
    sources so evidence is drawn from multiple independent providers.
    """
    if config.search_provider == "offline":
        _log.info("Using offline deterministic search provider")
        return OfflineSearchProvider()
    provider = CompositeSearchProvider(
        [
            WikipediaSearchProvider(),
            ArxivSearchProvider(),
            DuckDuckGoSearchProvider(),
        ]
    )
    _log.info("Using web search provider: %s", provider.name)
    return provider


def build_llm_provider(config: EngineConfig) -> LLMProvider:
    """Return the best available LLM provider given configuration.

    The provider is selected by ``config.llm_provider``; OpenRouter is the only
    live provider in v0.1. When disabled or unavailable (SDK/key missing), a null
    provider is returned and callers fall back to deterministic synthesis.
    """
    if not config.llm_enabled:
        return NullLLMProvider()

    provider = _build_configured_provider(config)
    if provider is not None and provider.available:
        _log.info(
            "Using %s LLM provider (%s)", config.llm_provider, config.llm_model
        )
        return provider

    _log.info(
        "LLM provider '%s' unavailable; using deterministic synthesis",
        config.llm_provider,
    )
    return NullLLMProvider()


def _build_configured_provider(config: EngineConfig) -> LLMProvider | None:
    """Construct the LLM provider named by the configuration, if recognized."""
    if config.llm_provider == "openrouter":
        return OpenRouterProvider(
            model=config.llm_model,
            base_url=config.llm_base_url,
            max_tokens=config.llm_max_tokens,
            timeout_seconds=config.llm_timeout_seconds,
            max_retries=config.llm_max_retries,
        )
    _log.warning("Unknown LLM provider '%s'; using deterministic synthesis", config.llm_provider)
    return None
