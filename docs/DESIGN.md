# Design Notes — Research Engine v0.1

This document records the concrete design of the v0.1 implementation. It
complements `ARCHITECTURE.md` (which defines the intended architecture) by
describing how that architecture is realized in code.

## Data flow and the shared contract

All subsystems communicate exclusively through the dataclasses in
`research_engine/domain/models.py`. No subsystem imports another subsystem's
implementation. The types trace the data flow:

```
ResearchRequest
  → Task[]                         (planner + taskgraph)
  → RawDocument[]                  (collection)
  → Source[] + Evidence[]          (processing)
  → Entity[] + Relationship[]      (knowledge graph)
  → Finding[] + Hypothesis[] + Contradiction[] + open_questions[]  (reasoning)
  → ResearchReport                 (report)
```

The `ResearchSession` aggregates all of the above and is the unit of
persistence, guaranteeing a report is reproducible from stored data.

## Subsystem responsibilities

- **Orchestrator** — owns the lifecycle and is the only place that knows the
  ordering of subsystems. Executes collection tasks in dependency order and is
  resilient to a failing source (a failed task is recorded; the run continues).
- **Planner** — deterministically decomposes a topic into domain-agnostic
  research angles plus a converging synthesis task.
- **Task graph** — a DAG with `topological_order()`; detects cycles and unknown
  dependencies. Ties break by insertion order for deterministic execution.
- **Collection** — pure acquisition; delegates to a `SearchProvider` and stamps
  provenance. No reasoning. The default provider is a `CompositeSearchProvider`
  fanning out across real no-key sources (Wikipedia + arXiv + DuckDuckGo), each
  isolated so one failure never breaks collection; `--offline` selects the
  deterministic stub.
- **Processing** — delegates extraction to a `ClaimExtractor` (LLM-backed over
  real source text — producing claims, entities, and relationships — or a
  deterministic heuristic fallback), then owns the strategy-independent concerns:
  global de-duplication, id assignment, provenance, and negation-based
  contradiction flagging. Every evidence item keeps its `source_id` and `task_id`.
- **Knowledge graph** — upserts entities and relationships. Co-occurrence within
  an evidence item yields generic `related_to` edges; LLM-extracted relationships
  promote those to typed, directed relations. Edge identity is the unordered
  entity pair, so the two never duplicate.
- **Reasoning** — one finding per collection task, synthesized from that angle's
  evidence; hypotheses grounded in the findings and strongest relationships;
  knowledge gaps; and an executive summary. Each LLM path (finding, hypothesis,
  summary) uses a light retry and has a deterministic fallback; confidence is
  scaled by source diversity and capped below certainty.
- **Report** — renders every section required by `PROJECT.md`, preserving
  citation links from findings → evidence → sources.
- **Storage** — writes `report/<topic>_report.md` and a JSON session snapshot.

## Extension points

The two provider interfaces in `research_engine/providers/base.py` are the seams
for future growth:

- Implement `SearchProvider` to add a real web/API/document source.
- Implement `LLMProvider` (or use the included OpenRouter provider) to add
  model-backed synthesis or extraction.

Reasoning and processing heuristics (entity extraction, contradiction detection,
finding synthesis) are each localized to a single method so they can be replaced
without changing callers.

## Reproducibility

Live runs are inherently non-deterministic: real sources change and the LLM
varies. Reproducibility is therefore a *mode*, not the default. Running with
`--offline --no-llm` makes the whole pipeline deterministic — planning, the
offline search provider, extraction, evidence ordering, entity ids (slugged
names), and confidence math — so given identical inputs the engine produces
identical research content. This is the mode the test suite uses. The structural
guarantee holds in every mode: a report is always fully reproducible from its
persisted session snapshot, since the snapshot stores the exact evidence used.
