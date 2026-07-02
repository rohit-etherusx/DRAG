"""Research Engine — a domain-agnostic autonomous research system.

The package is organized as a set of loosely-coupled subsystems that communicate
through the shared domain models in :mod:`research_engine.domain.models`:

* :mod:`research_engine.orchestrator` — coordinates the research lifecycle.
* :mod:`research_engine.planner` — turns an objective into a research task graph.
* :mod:`research_engine.taskgraph` — the directed research task graph.
* :mod:`research_engine.collection` — acquires raw information from sources.
* :mod:`research_engine.ranking` — ranks/filters documents by relevance and
  authority, and selects relevant passages, before processing.
* :mod:`research_engine.processing` — converts raw information into evidence.
* :mod:`research_engine.verification` — clusters equivalent claims across sources
  and measures agreement (corroboration).
* :mod:`research_engine.knowledge` — the knowledge graph of entities/relations.
* :mod:`research_engine.reasoning` — synthesizes findings, hypotheses, and
  deterministic confidence.
* :mod:`research_engine.report` — renders a Markdown research report.
* :mod:`research_engine.storage` — persists sessions and reports.
* :mod:`research_engine.providers` — pluggable search and LLM providers.
"""

__version__ = "0.3.0"
