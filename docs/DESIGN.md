# Design Notes — Research Engine v0.5

This document records the concrete design of the current implementation. It
complements `ARCHITECTURE.md` (which defines the intended architecture) by
describing how that architecture is realized in code. v0.5 is the
knowledge-first agent rewrite mandated by `OBJECTIVE.md`: research became an
iterative learning process over a single `ResearchState`, the planner stays
active for the whole run, curiosity turns missing knowledge into new searches,
information gain is measured per document and per iteration, stopping is an
explicit reasoned decision, and the report renders the completed knowledge
model instead of being the goal of the pipeline.

## Data flow and the shared contract

All subsystems communicate exclusively through the dataclasses in
`research_engine/domain/models.py` and the `ResearchState`. No subsystem
imports another subsystem's implementation. The types trace the data flow:

```
ResearchRequest
  → ResearchPlan + Task[]          (planner + taskgraph)
  → SearchTask[]                   (adaptive planning — every iteration)
  → SearchCandidate[]              (retrieval — metadata only)
  → SearchCandidate[] (accepted)   (candidate evaluation)
  → RawDocument[]                  (download; stamped with gain scores)
  → Evidence[]                     (passage extraction)
  → ExtractedClaim[] → Claim[]     (claim extraction → normalization)
  → Claim[] (verified, importance-stamped) + Contradiction[]
                                   (verification + importance)
  → GraphNode[]/GraphEdge[] + Entity[]     (knowledge builder)
  → KnowledgeGap[]                 (curiosity — fuel for the next iteration)
  → IterationRecord[]              (information gain per iteration)
  → Finding[] + Hypothesis[] + ConfidenceReport   (reasoning, every iteration)
  → Answer                         (answer generation — after the loop)
  → ResearchReport                 (rendering of the knowledge model)
```

`KnowledgeGap` and `SearchTask` are deliberately *domain* models: the curiosity
engine (reasoning layer) produces gaps into the state and the planner consumes
them from the state, so data flows upward through shared types while module
dependencies stay one-way.

The `ResearchSession` is rendered *from* the state (`ResearchState.to_session`)
at the end of a run — including the search-task audit trail, the gap history,
per-iteration gain records, and the stop reason — and remains the unit of
persistence. The provenance chain is explicit:
`Answer.claim_ids / Finding.claim_ids → Claim.evidence_ids →
Evidence.document_id/source_id`.

## The agent loop (orchestrator)

Per iteration, over one `ResearchState`:

1. **Adaptive planning** — `ResearchPlanner.next_search_tasks(state)`:
   iteration 1 executes the initial plan (one prioritized `SearchTask` per
   subquestion query, each carrying objective/reason/expected-information);
   later iterations first terminate satisfied branches
   (`state.complete_subquestion`), then convert the highest-priority open
   gaps into tasks. Queries that already ran are deterministically
   reformulated (angle rotation) rather than repeated; emitted tasks are
   recorded in the state and their gaps marked investigated.
2. **Acquisition** — per task: `RetrievalManager.search` (stateless; the state
   owns the visited-URL history) → `CandidateEvaluator` (metadata-only gate) →
   `download` (accepted only) → `EvidenceProcessor` (passages → typed claims).
   Failures are isolated per task and recorded on the state.
3. **Knowledge update** — normalize the full accumulated claim set, verify
   (see below), `KnowledgeBuilder.build` (entity alias merging + graph),
   `ImportanceModel.stamp` (see below), `state.set_knowledge`.
4. **Reasoning** — `ReasoningEngine.analyze` over the claims at or above
   `min_claim_importance` (fail-open if the filter would empty the set):
   per-subquestion findings, patterns, hypotheses, weak subquestions, and the
   overall explained `ConfidenceReport`. Runs every iteration — reasoning
   drives research.
5. **Curiosity** — `CuriosityEngine.discover`: missing evidence /
   uncorroborated subquestions, undefined or unconnected central entities,
   contradictions, and important claims lacking an authoritative source — each
   gap with a suggested query and priority. `state.add_gaps` de-duplicates by
   (kind, subquestion, entity) so re-discovery never re-opens investigated
   gaps.
6. **Information gain** — `InformationGainAnalyzer.analyze` stamps each new
   document's novelty/coverage/redundancy/evidence-density/importance (claim
   identity = the normalizer's `claim_signature`) and records an
   `IterationRecord` (novelty, knowledge gain = the fraction of the current
   model this iteration contributed, confidence, open gaps).
7. **Stopping** — `StoppingEngine.decide` (first match wins): confidence
   target reached · no actionable gaps · budget exhausted · knowledge gain
   below `min_iteration_gain` · confidence stabilized (delta below
   `min_confidence_delta`). The reason is persisted as `session.stop_reason`.

After the loop: `AnswerGenerator.generate` synthesizes the `Answer` (text,
reasoning, confidence, claim citations, remaining uncertainty) from the
importance-ranked verified claims — for questions *and* topics — plus the
executive summary; then the report renders and the session persists.

## Verification (v0.5 upgrade)

Live v0.4 runs corroborated ~0% of claims: plain Jaccard similarity weighted
ubiquitous topic words as heavily as distinctive ones, so genuine cross-source
paraphrases scored *below* unrelated same-topic claims. v0.5 replaces it with:

- **Rarity-weighted clustering** (`verification/clustering.py`) — tokens are
  weighted by `log(1 + N/df)` computed over the run's own claims; similarity
  is the weighted Jaccard. Guards: polarity (negations contradict, never
  corroborate) and numeric conflict ("28.4 BLEU" vs "41.8 BLEU" never merge).
  Auto-merge stays conservative (near-identical wordings only) because a
  false merge fabricates corroboration.
- **Borderline band + equivalence judge** — `ClaimClusterer.borderline_pairs`
  exposes the cluster-seed pairs too similar to dismiss but not similar enough
  to merge; `LLMEquivalenceJudge` (one strict-JSON call per batch, capped by
  `max_equivalence_checks`) decides which assert the same fact. Accepted
  verdicts merge via union-find in `ClaimVerifier`. Every failure path
  degrades to "not equivalent", so the judge can only add corroboration the
  clusterer missed — and offline runs remain fully deterministic.

## Claim importance

`reasoning/importance.py` — a pure function of type value (definitions and
methods teach more than stray dates), objective relevance (claim vocabulary ∩
plan vocabulary), entity centrality (claims about entities the model keeps
referencing), and corroboration (`agreement`). Stamped on every verified
claim; used to filter reasoning input, rank answer support, and order the
report's Verified Claims section. Importance is not confidence: a contradicted
claim can be important while its confidence is low.

## Subsystem responsibilities (delta from v0.4)

- **`state/research_state.py`** — new. The single source of truth during a
  run: plan + subquestion lifecycle, search history + visited URLs + failures,
  all acquired artifacts, the knowledge model, gaps, iteration records,
  confidence history, stop reason. All mutations go through its methods;
  `to_session()` renders the persistent snapshot.
- **Planner** — plans once, then *stays active*: `next_search_tasks` +
  `_terminate_satisfied_branches` (a branch completes when claims support it
  and no open gap targets it). `follow_up_queries` (v0.4) was replaced by
  gap-driven planning.
- **Retrieval** — `RetrievalManager` is now stateless; `search(task,
  exclude_urls)` executes one `SearchTask`.
- **Knowledge** — `knowledge/builder.py` (new) canonicalizes entity aliases
  (case/possessive/naive-plural folding; most frequent spelling wins,
  deterministically) before delegating graph construction to the existing
  `EvidenceGraph`.
- **Reasoning** — `analyzer.py` no longer produces the direct answer or the
  executive summary (moved to `answer.py`, which runs on the completed
  knowledge model); new modules: `importance.py`, `gain.py`, `curiosity.py`,
  `stopping.py`.
- **Report** — renders the knowledge model: the Answer section (questions and
  topics; citations, reasoning, remaining uncertainty), importance-ordered
  Verified Claims (top 25 in print, the rest preserved in the snapshot), a
  Knowledge Gaps section (investigated vs. open), and a Research Iterations
  appendix table with the stop reason.
- Everything else (task graph, candidate evaluation, passage selection, claim
  extraction, normalization, confidence model, storage, providers, CLI/API
  surfaces) carries over from v0.4 unchanged in interface.

## Configuration (new in v0.5)

`min_claim_importance` (0.1), `min_iteration_gain` (0.05),
`min_confidence_delta` (0.02), `max_search_tasks_per_iteration` (6),
`max_equivalence_checks` (40), and `max_iterations` raised to 3. All have
`RE_*` environment equivalents; see `.env.example`.

## Extension points

The two provider interfaces in `research_engine/providers/base.py` remain the
seams for new sources and models. New deterministic components that can be
upgraded behind their existing interfaces: `ClaimEquivalenceJudge` (swap in an
embedding-based judge), the curiosity heuristics, the importance weights, the
gain formula, and the stopping criteria. The contradiction heuristic and
`classify_claim` remain documented seams from v0.4.

## Reproducibility

Unchanged in principle: `--offline --no-llm` makes the whole run deterministic
— planning, adaptive planning, evaluation, extraction, normalization,
clustering (no judge without an LLM), importance, gain, curiosity, stopping,
and all confidence math — so identical inputs produce identical research
content. The test suite (168 tests, network-free) exercises exactly this mode,
including determinism across runs, gap-driven iteration, and explicit stop
reasons. The structural guarantee holds in every mode: a report is always
fully reproducible from its persisted session snapshot.
