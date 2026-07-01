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
  provenance. No reasoning.
- **Processing** — splits content into claims, de-duplicates, extracts candidate
  entities, and flags negation-based contradictions. Every evidence item keeps
  its `source_id` and `task_id`.
- **Knowledge graph** — upserts entities and infers `related_to` relationships
  from entity co-occurrence within an evidence item.
- **Reasoning** — one finding per collection task (confidence scaled by source
  diversity, capped below certainty), hypotheses from the strongest
  relationships, knowledge gaps, and an executive summary (LLM-optional with a
  deterministic fallback).
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

Every default is deterministic: planning, the offline search provider, evidence
ordering, entity ids (slugged names), and confidence math. Given identical
inputs and providers, the engine produces identical research content. Only
timestamps and the optional LLM narrative are non-deterministic, and neither is
part of the structured evidence.
