"""Real, no-key data-source providers.

Each module implements a :class:`~research_engine.providers.base.SearchProvider`
against a public, no-authentication source (Wikipedia, arXiv, DuckDuckGo). The
:class:`~research_engine.providers.sources.composite.CompositeSearchProvider`
fans a query out across several of them and merges the results, giving the engine
evidence drawn from multiple independent sources.
"""
