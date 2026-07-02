# Design Notes — Research Engine v0.4

This document records the concrete design of the current implementation. It
complements `ARCHITECTURE.md` (which defines the intended architecture) by
describing how that architecture is realized in code. v0.4 is the claim-centric
rewrite mandated by `OBJECTIVE.md`: documents became evidence containers, the
verified claim became the reasoning unit, retrieval became two-phase
(evaluate-before-download), and the whole pipeline runs inside an iterative
research loop.

## Data flow and the shared contract

All subsystems communicate exclusively through the dataclasses in
`research_engine/domain/models.py`. No subsystem imports another subsystem's
implementation. The types trace the data flow:

```
ResearchRequest
  → ResearchPlan + Task[]          (planner + taskgraph)
  → SearchCandidate[]              (retrieval — metadata only)
  → SearchCandidate[] (accepted)   (candidate evaluation)
  → RawDocument[]                  (download, accepted candidates only)
  → Evidence[]                     (passage extraction)
  → ExtractedClaim[] → Claim[]     (claim extraction → normalization)
  → Claim[] (verified) + Contradiction[]   (verification)
  → GraphNode[]/GraphEdge[] + Entity[]     (evidence graph)
  → Finding[] + Hypothesis[] + ConfidenceReport + direct answer  (reasoning)
  → ResearchReport                 (adaptive report)
```

The `ResearchSession` aggregates all of the above — including the full
candidate audit trail and retrieval statistics — and is the unit of
persistence, guaranteeing a report is reproducible from stored data. The
provenance chain is explicit: `Finding.claim_ids → Claim.evidence_ids →
Evidence.document_id/source_id`.

## Subsystem responsibilities

- **Orchestrator** — owns the lifecycle and the research loop; the only place
  that knows the running order. Per iteration it retrieves/evaluates/downloads/
  processes each targeted subquestion (failures recorded per task, run
  continues), then normalizes, verifies, rebuilds the graph, and reasons over
  the *full accumulated* claim set. Loop control: stop at
  `confidence >= confidence_threshold`, when no weak subquestions remain, or at
  the `max_iterations` budget. Follow-up iterations use the planner's
  deterministic query reformulations and only target the weak subquestions.
- **Planner** — produces the structured `ResearchPlan` (objective,
  subquestions + search queries, expected entities/evidence/source types,
  scope, exclusion criteria). LLM planning returns strict JSON (retried,
  validated); the deterministic planner detects question-shaped input
  (interrogative opener or trailing `?`), extracts the subject, and decomposes
  questions into answer-targeted subquestions vs. topics into domain-agnostic
  facets. Also derives the task graph and research-loop follow-up queries.
- **Task graph** — a DAG with `topological_order()`; detects cycles and unknown
  dependencies. One collect task per subquestion (bound via `subquestion_id`),
  one converging synthesis task.
- **Retrieval (`collection/`)** — two-phase acquisition, no reasoning.
  `retrieve()` runs each subquestion query independently through
  `SearchProvider.search_candidates()` (metadata only), merges and de-dupes by
  URL globally across the session (iterations never re-fetch known results).
  `download()` calls `fetch()` for accepted candidates only, isolating
  per-candidate failures.
- **Candidate evaluation (`ranking/evaluator.py`)** — the pre-download gate.
  Operates only on title/snippet/URL/provider: stamps deterministic authority
  (`SourceAuthorityScorer`: domain/TLD/provider → tier), scores relevance as
  term coverage of the subquestion + plan subject + expected entities
  (title-weighted, fail-open with no terms), applies the plan's exclusion
  criteria, drops duplicate titles, thresholds relevance/authority, and keeps
  the top-N survivors per subquestion (N = `documents_per_query`). Rejected
  candidates carry their reason; all candidates land in the session.
- **Passage extraction (`ranking/passages.py`)** — `PassageSelector.top_passages`
  splits a document (paragraphs, falling back to sentence windows), scores each
  passage against the subquestion, and returns the best few in document order
  with scores. Fail-open: if nothing qualifies the whole document is one
  passage. `processing/processor.py` turns these into `Evidence` items with
  global de-duplication and sequential ids.
- **Claim extraction (`processing/extraction.py`)** — `ClaimExtractor` turns a
  document's evidence passages into typed `ExtractedClaim`s.
  `HeuristicClaimExtractor`: one claim per sentence, type via ordered
  deterministic rules (`classify_claim`: open-question → definition →
  assumption → limitation → method → date → numerical → fact), entities via
  capitalized-phrase spotting. `LLMClaimExtractor`: one strict-JSON prompt per
  document over its numbered passages (never the raw document), type validated
  against the enum, passage index mapped back to the evidence id; retries then
  falls back to the heuristic.
- **Normalization (`processing/normalizer.py`)** — merges identical-signature
  claims (sorted content words) into canonical claims: longest wording wins,
  others become `variants`; evidence/source/subquestion/entity references are
  unioned; a specific claim type beats `FACT`. "not" is *not* a stopword here,
  so polarity differences never merge.
- **Verification (`verification/`)** — `ClaimClusterer` groups near-equivalent
  claims (token-set Jaccard ≥ 0.6, ≥ 3 shared tokens, same negation polarity —
  a negated claim can contradict, never corroborate). `ClaimVerifier` merges
  each cluster into one canonical claim (ids reassigned contiguously), stamps
  agreement (`(sources-1)/3` capped, + domain-diversity bonus), detects
  contradictions (shared vocabulary, opposite polarity), links them from both
  claims, and assigns `VerificationStatus`
  (contradicted / corroborated / single_source).
- **Evidence graph (`knowledge/graph.py`)** — `EvidenceGraph` builds typed
  nodes (claim primary; evidence, document, entity secondary) and edges:
  evidence—`supports`→claim, evidence—`references`→document,
  claim—`defines`→entity (definition claims, first entity),
  claim—`references`→entity, claim—`contradicts`→claim,
  detail(numerical/date)—`extends`→definition and method—`depends_on`→assumption
  for claims sharing an entity. Query surface: `central_entities`,
  `claims_for_entity`, `edges_by_relation`.
- **Confidence (`reasoning/confidence.py`)** — a pure function of measurable
  inputs: independent sources, independent domains, mean authority, agreement,
  contradictions, coverage of the plan, evidence quality, claim specificity
  (typed: numbers/dates most specific, open questions least). Fixed documented
  weights; claim-level scores pass `coverage=None` and the weights renormalize.
  Capped at 0.95 (never certain). `report()` returns a `ConfidenceReport` with
  every factor and a generated plain-language explanation; `explain()` is used
  for claim- and finding-level explanations too.
- **Reasoning (`reasoning/analyzer.py`)** — inputs are verified claims, the
  evidence graph, and the plan; never documents. Stamps explained confidence on
  every claim; builds one finding per answerable subquestion from its claims
  (preferring claims whose primary subquestion matches, so findings stay
  distinct); flags subquestions with no or only single-source evidence as
  missing evidence + research-loop targets; derives patterns (entities spanning
  subquestions), hypotheses (LLM grounded in findings, deterministic
  entity-co-occurrence fallback), open questions (open-question claims +
  contradictions), and the overall `ConfidenceReport` (coverage = answered
  subquestions / total). For question-shaped plans it synthesizes a **direct
  answer** from the strongest non-contradicted claims (LLM or deterministic).
  Every LLM path: light retry → deterministic fallback.
- **Report (`report/generator.py`)** — adaptive: each section renders only when
  the session supports it; a question without a derivable answer states that
  explicitly; missing evidence and single-source caveats get their own section.
  Citation chain in print: findings cite claim ids; each verified claim line
  shows type, status, sources/domains/agreement, and `evidence → source-label`
  provenance; the appendix carries retrieval/verification statistics and the
  labelled sources with authority tiers.
- **Storage** — writes `report/<topic>_report.md` and a JSON session snapshot
  (dataclasses/enums serialized generically, so new model fields persist
  automatically).

## Extension points

The two provider interfaces in `research_engine/providers/base.py` are the seams
for future growth:

- Implement `SearchProvider` (`search_candidates` + `fetch`) to add a real
  web/API/document source — the two-phase shape is what lets candidate
  evaluation protect the download budget.
- Implement `LLMProvider` (or use the included OpenRouter provider) to add
  model-backed planning/extraction/synthesis.

Deterministic components that can be upgraded behind their existing seams:
`ClaimClusterer` (semantic clustering), the contradiction heuristic in
`verification/verifier.py`, `classify_claim`, the relevance scoring in
`ranking/evaluator.py`, and `ConfidenceModel`'s documented weights.

## Reproducibility

Live runs are inherently non-deterministic: real sources change and the LLM
varies. Reproducibility is therefore a *mode*, not the default. Running with
`--offline --no-llm` makes the whole pipeline deterministic — planning,
candidate generation and evaluation, passage selection, claim extraction and
typing, normalization, clustering, agreement, graph construction, and all
confidence math — so identical inputs produce identical research content
(claims, findings, confidence). This is the mode the test suite uses. The
structural guarantee holds in every mode: a report is always fully reproducible
from its persisted session snapshot, since the snapshot stores the exact
evidence and claims used.
