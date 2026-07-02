# Design Notes — Research Engine v0.3

This document records the concrete design of the current implementation. It
complements `ARCHITECTURE.md` (which defines the intended architecture) by
describing how that architecture is realized in code. v0.3 adds an
evidence-quality gate (ranking/filtering/passage selection) and a verification +
deterministic-confidence stage; both fit the existing architecture without any
interface breakage.

## Data flow and the shared contract

All subsystems communicate exclusively through the dataclasses in
`research_engine/domain/models.py`. No subsystem imports another subsystem's
implementation. The types trace the data flow:

```
ResearchRequest
  → Task[]                         (planner + taskgraph)
  → RawDocument[]                  (collection)
  → RawDocument[] (scored/filtered/trimmed)        (ranking)
  → Source[] + Evidence[]          (processing)
  → ClaimCluster[]                 (verification)
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
- **Ranking** *(v0.3)* — the evidence-quality gate between collection and
  processing. `SourceAuthorityScorer` assigns a deterministic authority tier by
  domain/provider; a `RelevanceScorer` (heuristic term-coverage by default, LLM
  drop-in available) scores topical relevance. `DocumentRanker` stamps both,
  rejects sub-threshold documents (they never reach processing or the graph), and
  `PassageSelector` trims accepted documents to their relevant passages (fail-open)
  to cut extraction tokens. Authority informs confidence; relevance is the
  rejection gate. Disabling ranking reproduces v0.2 behaviour exactly.
- **Processing** — delegates extraction to a `ClaimExtractor` (LLM-backed over
  real source text — producing claims, entities, and relationships — or a
  deterministic heuristic fallback), then owns the strategy-independent concerns:
  global de-duplication, id assignment, provenance, and negation-based
  contradiction flagging. Every evidence item keeps its `source_id`, `task_id`,
  and the relevance of its source document.
- **Verification** *(v0.3)* — `ClaimClusterer` groups equivalent claims across
  sources (deterministic token-Jaccard; an LLM clusterer could replace it behind
  the same signature). `EvidenceVerifier` records, per cluster, the number of
  independent sources and domains and an `agreement` strength. This corroboration
  feeds confidence and the report's Evidence Verification section.
- **Knowledge graph** — upserts entities and relationships. Co-occurrence within
  an evidence item yields generic `related_to` edges; LLM-extracted relationships
  promote those to typed, directed relations. Edge identity is the unordered
  entity pair, so the two never duplicate.
- **Reasoning** — one finding per collection task, synthesized from that angle's
  evidence; hypotheses grounded in the findings and strongest relationships;
  knowledge gaps; and an executive summary. Each LLM path (finding, hypothesis,
  summary) uses a light retry and has a deterministic fallback. Confidence is now
  computed by `ConfidenceModel` (`reasoning/confidence.py`) — a pure, deterministic
  function of measurable inputs (supporting sources, independent domains, mean
  source authority, claim agreement, contradiction count, mean relevance) with
  fixed weights, capped below certainty. Identical inputs always yield the
  identical score.
- **Report** — renders every section required by `PROJECT.md` plus an Evidence
  Verification section, preserving citation links from findings → evidence →
  sources. Findings are synthesized (agreement / disagreement / uncertainty) and
  citations carry source authority.
- **Storage** — writes `report/<topic>_report.md` and a JSON session snapshot.

## Extension points

The two provider interfaces in `research_engine/providers/base.py` are the seams
for future growth:

- Implement `SearchProvider` to add a real web/API/document source.
- Implement `LLMProvider` (or use the included OpenRouter provider) to add
  model-backed synthesis or extraction.

v0.3 adds three more seams, each an interface with a deterministic default:
`RelevanceScorer` (heuristic or LLM), the claim `ClaimClusterer` (token-similarity
or a future semantic clusterer), and `ConfidenceModel` (a documented weighting
that can be tuned or swapped). `SourceAuthorityScorer`'s domain→tier table is a
single, legible data structure that is trivial to extend.

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
