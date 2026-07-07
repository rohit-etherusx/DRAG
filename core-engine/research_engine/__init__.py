"""Research Engine — a domain-agnostic, claim-centric autonomous research system.

The package is organized as a set of loosely-coupled subsystems that communicate
through the shared domain models in :mod:`research_engine.domain.models`.
Documents are evidence containers; the primary reasoning unit is the verified
claim, and the provenance chain (finding → claim → evidence → document →
source) is preserved end to end.

* :mod:`research_engine.orchestrator` — coordinates the lifecycle + research loop.
* :mod:`research_engine.planner` — understands the question; produces the plan.
* :mod:`research_engine.taskgraph` — the directed research task graph.
* :mod:`research_engine.collection` — targeted retrieval + download of accepted
  candidates.
* :mod:`research_engine.ranking` — candidate evaluation (metadata-only gate),
  source authority, passage selection.
* :mod:`research_engine.processing` — passage extraction, typed claim
  extraction, claim normalization.
* :mod:`research_engine.verification` — cross-source claim verification
  (clustering, agreement, contradictions).
* :mod:`research_engine.knowledge` — the claim-centric evidence graph.
* :mod:`research_engine.reasoning` — reasoning over verified claims +
  deterministic, explained confidence.
* :mod:`research_engine.report` — adaptive Markdown research reports.
* :mod:`research_engine.storage` — persists sessions and reports.
* :mod:`research_engine.providers` — pluggable two-phase search + LLM providers.
"""

__version__ = "0.6.0"
