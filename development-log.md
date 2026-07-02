# development-log.md

Running progress log for the Research Engine (see `OBJECTIVE.md`).

Per `OBJECTIVE.md`, this is the single running progress log. `TASKS.md` holds the
implementation plan / task board; this file records what was actually done, why,
and what remains. Newest entries first.

---

## Entry 5 — v0.5: autonomous research agent (T70–T84)

**Date:** 2026-07-02

### Completed

The knowledge-first agent rewrite mandated by `OBJECTIVE.md` v0.5: research is
now an iterative learning loop over a persistent research state; the answer is
the product and the report is a rendering of the knowledge model.

- **T70–T71 contracts + config**: new domain models (`KnowledgeGap`/`GapKind`,
  `SearchTask` with objective/reason/expected-information/priority,
  `IterationRecord`, `Answer`; `Claim.importance`; per-document gain scores;
  session additions: `answer`, `search_tasks`, `knowledge_gaps`,
  `iteration_records`, `stop_reason`). New knobs: `min_claim_importance`,
  `min_iteration_gain`, `min_confidence_delta`,
  `max_search_tasks_per_iteration`, `max_equivalence_checks`;
  `max_iterations` default raised to 3.
- **T72 ResearchState** (`state/`): the single source of truth during a run —
  subquestion lifecycle, search history + visited URLs + failures, all
  acquired artifacts, the knowledge model, gap queue (identity-deduped),
  iteration records, confidence history; `to_session()` renders the snapshot.
  `RetrievalManager` became stateless accordingly.
- **T73 verification upgrade** (root-caused from a live run that corroborated
  0/100 then 1/164 claims): rarity-weighted (in-run IDF) Jaccard clustering
  with polarity and numeric-conflict guards — conservative auto-merge — plus a
  borderline band submitted to a new `LLMEquivalenceJudge`
  (`verification/equivalence.py`, one strict-JSON call, union-find merge,
  fails closed to "not equivalent"). Offline behavior stays deterministic.
- **T74 claim importance** (`reasoning/importance.py`): deterministic 0..1
  score (type value, objective relevance, entity centrality, corroboration);
  filters reasoning input, ranks answer support, orders the report.
- **T75 knowledge builder** (`knowledge/builder.py`): entity alias merging
  (case/possessive/naive-plural; most frequent spelling wins) before graph
  construction via the existing `EvidenceGraph`.
- **T76 information gain** (`reasoning/gain.py`): per-document novelty /
  coverage / redundancy / evidence-density / importance (claim identity =
  `claim_signature`); per-iteration novelty + knowledge gain records.
- **T77 curiosity** (`reasoning/curiosity.py`): gaps for missing/uncorroborated
  subquestion evidence, undefined or unconnected central entities,
  contradictions, and important claims lacking authoritative sources — each
  with a suggested query and priority.
- **T78 adaptive planner**: `next_search_tasks(state)` — initial plan on
  iteration 1, prioritized gap-driven tasks afterwards, deterministic query
  reformulation instead of repeats, satisfied-branch termination. Replaces
  `follow_up_queries`.
- **T79 stopping engine** (`reasoning/stopping.py`): explicit, recorded
  decisions — confidence target · no actionable gaps · budget · negligible
  gain · confidence stabilized.
- **T80 answer generator** (`reasoning/answer.py`): `Answer` (text, reasoning,
  confidence, claim citations, remaining uncertainty) synthesized from the
  importance-ranked knowledge model for questions *and* topics; executive
  summary moved here from the analyzer.
- **T81 orchestrator rewrite**: the agent loop (plan → state → search tasks →
  acquire → verify → build knowledge → importance → reason → curiosity → gain
  → stopping), then answer, report, persistence. `run_research`/CLI/API
  surfaces unchanged.
- **T82 report renderer**: Answer section (citations + reasoning + remaining
  uncertainty), importance-ordered Verified Claims, Knowledge Gaps
  (investigated vs. open), Research Iterations table + stop reason in the
  appendix.
- **T83 tests**: 125 → **168** network-free tests — new suites for state,
  importance/gain/curiosity/stopping, knowledge builder, equivalence judge and
  clustering guards; planner/reasoning/report suites updated to the replaced
  interfaces; e2e now asserts agent-loop artifacts (search-task audit,
  iteration records, stop reason, gap-driven second-iteration searches,
  determinism).
- **T84 docs**: `docs/DESIGN.md` rewritten for v0.5, `README.md` updated,
  `.env.example` extended, version bumped to 0.5.0.

### Notes / carried debt

- Wikipedia 429 rate-limiting under multi-iteration runs is recorded as v0.6
  networking scope (retry/backoff is a performance concern, out of v0.5 scope).
- Contradiction detection remains the deterministic negation/overlap
  heuristic; the equivalence-judge seam shows where a semantic version drops
  in.
- ~~Pending sign-off~~ **Live grounded run completed** (2026-07-02, topic
  "quantum tunneling", web sources + `deepseek/deepseek-v4-flash`, ~16 min):
  - Agent loop: 3 iterations; iter 2 ran 6 gap-driven searches (from 6 gaps:
    2 missing-evidence, 3 uncorroborated, 2 contradictions), iter 3 ran 2 and
    found nothing new → stopped with recorded reason **"no actionable
    knowledge gaps remain"** (v0.4 stopped only on budget exhaustion).
  - Information gain tracked the learning curve: novelty 100%→100%→0%, gain
    100%→21%→0%, confidence 43%→49%→49%.
  - Verification: 161 claims, **3 corroborated with genuine cross-source
    paraphrase variants** (e.g. two independent definitions of tunneling) and
    zero observed false merges. The equivalence judge reviewed 13–17
    borderline pairs per pass and accepted 3 — selective, as designed. v0.4's
    same-scale run: 164 claims, 1 corroborated (a fabricated merge risk).
  - Claim importance ranked definitions of tunneling/QM at the top (0.61…)
    and boilerplate at the bottom; the answer cited the top-importance claims.
  - Extraction fallback fired on 3 of 21 documents (model-dependent strict-JSON
    quality, known debt); importance filtering absorbed the resulting noise.
  - Corroboration rate (3/161) remains bounded by real cross-source paraphrase
    scarcity at sentence grain — sub-sentence fact alignment is future work.

---

## Entry 4 — v0.4: claim-centric architecture rewrite (T53–T69)

**Date:** 2026-07-02

### Completed

The full pipeline rewrite mandated by the updated `OBJECTIVE.md`: documents are
now evidence containers and the **verified claim** is the reasoning unit.

- **T53–T54 contracts**: new domain models (`ResearchPlan`/`SubQuestion`,
  `SearchCandidate`, passage-level `Evidence`, typed `Claim` with verification
  metadata, `ClaimType`/`VerificationStatus`/`EdgeRelation` enums,
  `GraphNode`/`GraphEdge`, `ConfidenceReport`); session restructured (plan,
  candidate audit trail, claims, graph, direct answer, missing evidence,
  iteration/efficiency stats). New config knobs: `evaluation_enabled`,
  `max_candidates_per_query`, `candidate_relevance_threshold`,
  `confidence_threshold`, `max_iterations`.
- **T55 two-phase retrieval**: `SearchProvider` split into
  `search_candidates()` (title/snippet/URL only) + `fetch()` (one accepted
  candidate). Wikipedia (search list → extract on fetch), DuckDuckGo (lite
  results → page fetched only on accept), arXiv (feed cached at search; fetch
  is free), offline (deterministic candidates + synthesized fetch — the whole
  gate is exercised offline), composite (fan-out, URL dedupe, fetch routed to
  the owning provider).
- **T56 planner**: structured `ResearchPlan` via LLM strict-JSON with a
  deterministic question-aware fallback — question detection, subject
  extraction, answer-targeted subquestions for questions vs. facet
  decomposition for topics (implements the thesis.md "question-driven
  research" analysis, now in scope per the new objective). Task graph derived
  from the plan; deterministic follow-up-query generation for the loop.
- **T57–T58 retrieval manager + candidate evaluator**: per-subquestion
  independent searches, global URL dedupe across iterations; metadata-only
  gate (relevance from title/snippet term coverage, deterministic authority,
  exclusion criteria, duplicate titles, per-subquestion budget) with recorded
  rejection reasons. Superseded `ranking/ranker.py` + `ranking/relevance.py`
  removed.
- **T59–T61 claim pipeline**: `PassageSelector.top_passages` → passage-level
  `Evidence`; typed claim extraction (deterministic `classify_claim` rule
  chain; LLM extractor prompts over numbered passages and maps claims back to
  evidence ids); deterministic `ClaimNormalizer` (signature merge, variants,
  provenance union).
- **T62 verification engine**: clusters equivalent claims (same-polarity only —
  negations contradict, never corroborate), merges clusters into canonical
  claims, stamps agreement/independent-domain metadata, detects and links
  contradictions, flags unsupported single-source claims.
- **T63 evidence graph**: claim-primary typed graph (supports / contradicts /
  extends / depends_on / defines / references) replacing the entity graph.
- **T64–T65 confidence + reasoning**: confidence extended with coverage and
  claim-specificity factors, per-factor `ConfidenceReport` + generated
  plain-language explanation at claim/finding/overall level (claim-level
  renormalizes away the coverage weight); reasoning consumes only verified
  claims + graph + plan — findings per answerable subquestion, **direct
  answer** for question input, patterns, missing evidence (drives the loop),
  hypotheses, open questions.
- **T66 adaptive report**: sections render only when supported; unanswerable
  questions and evidence gaps are stated explicitly; full printed provenance
  chain (finding → claim → evidence → source) plus retrieval statistics.
- **T67 orchestrator + research loop**: iterate retrieval → verification →
  confidence until threshold reached, no actionable gaps remain, or
  `max_iterations` exhausted; follow-up iterations target only weak
  subquestions with reformulated queries. CLI/API preserved (flags additive:
  `--max-iterations`, `--confidence-threshold`).
- **T68–T69 quality + docs**: test suite rewritten for the new architecture —
  **125 tests, all green, network-free** (two-phase sources, planner, candidate
  evaluator, claim pipeline, verification, evidence graph, explained
  confidence, reasoning, adaptive report, e2e determinism + loop budget +
  failing-provider resilience). Docs synced: `ARCHITECTURE.md` (new pipeline,
  as required by the objective), `README.md`, `instructions.md`,
  `docs/DESIGN.md`, `.env.example`. Version **0.4.0**.

### Architectural decisions & tradeoffs

- **Two-phase `SearchProvider` is a breaking interface change** (the objective
  explicitly prioritizes correctness over backward compatibility; CLI/API
  surfaces are unchanged). It is the mechanism behind the "reduce irrelevant
  downloads ≥80%" goal: rejection happens before any page fetch. Offline smoke
  run: 48 candidates evaluated, 30 rejected pre-download, 18 fetched.
- **Cluster-merge instead of cluster-annotate**: verification merges equivalent
  claims into one canonical claim (ids reassigned contiguously afterwards)
  rather than keeping duplicates with cluster labels — downstream reasoning
  and reports stay clean, and variants preserve the original wordings.
- **Polarity guard in clustering**: "X is effective" and "X is not effective"
  previously token-matched as equivalent; clustering now refuses to merge
  across negation polarity so contradictions survive to be detected (caught by
  a test during the rewrite).
- **LLM usage is confined to semantic tasks** (planning, claim extraction,
  phrasing of findings/answers/hypotheses/summaries), each with retry +
  deterministic fallback; all measurement (relevance, authority, clustering,
  agreement, coverage, specificity, confidence) is deterministic per the
  objective.
- **Claim-level vs. plan-level confidence**: one documented weight set; claim
  scores pass `coverage=None` and renormalize, avoiding a second formula.

### Known limitations / future work

- Corroboration ≠ ground truth: widely repeated errors corroborate each other.
- Contradiction detection remains the negation/overlap heuristic (semantic
  detection is a seam in `verification/verifier.py`).
- Candidate relevance is judged from titles/snippets; a well-written page with
  a poor title can be rejected at the gate (thresholds configurable).
- The LLM extractors/planner still depend on the configured model's JSON
  discipline; weak models fall back to heuristics more often.
- Pending: a live grounded run (network + `OPENROUTER_API_KEY`) to measure the
  download/token-reduction objectives on real sources.

---

## Entry 3 — Verification, deterministic confidence, report synthesis (T47–T52)

**Date:** 2026-07-02

### Completed
- **T47–T48 `verification/` package**: `ClaimClusterer` groups equivalent claims
  across sources (deterministic token-Jaccard); `EvidenceVerifier` produces
  `ClaimCluster`s with `supporting_sources`, `independent_domains`, and an
  `agreement` strength, plus per-evidence lookups. Wired into the orchestrator;
  `session.claim_clusters` populated when `verification_enabled`.
- **T50 deterministic confidence** (`reasoning/confidence.py`): `ConfidenceModel`
  turns measurable inputs (supporting sources, independent domains, mean
  authority, agreement, contradictions, mean relevance) into a reproducible 0..1
  score via fixed weights, capped at 0.95. `ReasoningEngine` now derives
  per-finding confidence from it (replacing the old source-count ratio); `analyze`
  gained optional `sources` + `verification` params (backward-compatible).
- **T51 report synthesis**: each finding is annotated with its evidential standing
  (sources, independent corroboration, conflicts, remaining uncertainty); new
  **Evidence Verification** section (retrieved/accepted/rejected counts +
  corroborated claims); citations now show source authority tier + score.
- **T49 (partial)**: contradictions now *reduce confidence* (fed into the model)
  and are reported per-finding and in the Contradictions section — meeting problem
  8's required outcomes. The detector remains the deterministic negation/overlap
  heuristic; semantic (embedding/LLM) comparison is a documented seam.
- **T52**: version bumped to **0.3.0** (`pyproject.toml`, `__init__`); docs synced
  (`instructions.md`, `docs/DESIGN.md`, `.env.example`); tests added
  (`test_confidence.py`, verification + report tests). **Full suite: 96 pass.**

### Design decisions
- Confidence is a **pure function** — no LLM, no randomness — so identical inputs
  give identical scores (`OBJECTIVE.md` problem 7). Weights are documented
  constants in one module and easy to tune.
- Clustering uses unordered content-token Jaccard (≥0.6, ≥3 shared tokens):
  deterministic, domain-agnostic, and cheap. An LLM/semantic clusterer can
  replace it behind `ClaimClusterer.cluster` without touching callers.
- `agreement` rewards independent *domains*, not just repeated assertions, so
  three copies of a claim from one domain count for less than three domains.

### Token usage changes
- **Structural, measured on a controlled mixed set** (8 docs, half irrelevant,
  with filler paragraphs): input characters reaching extraction dropped **~94%**
  (13,656 → 808 chars; ~3,400 → ~200 tokens) via relevance rejection + passage
  trimming. Real-world savings depend on the document mix; a live grounded run is
  the outstanding measurement (needs network + `OPENROUTER_API_KEY`).

### Unresolved issues / blockers
- None blocking. Outstanding before formal v0.3 sign-off: one **live grounded
  run** to validate token reduction and the LLM extraction/relevance/reasoning
  paths on real sources, and a short README refresh.

### Remaining work
- Live grounded verification run (owner to approve/trigger — consumes tokens).
- Optional: enable `LLMRelevanceScorer` by config flag; README v0.3 refresh.

---

## Entry 2 — Foundations + ranking gate (T40–T46)

**Date:** 2026-07-02

### Completed
- **T40 domain models** (additive, serialization-safe): `Source.domain`,
  `Source.authority`, `Source.authority_tier`; `RawDocument.relevance_score`;
  `Evidence.relevance_score`; new `ClaimCluster` model; `ResearchSession`
  gained `claim_clusters` and `rejected_documents`.
- **T41 config**: `ranking_enabled`, `relevance_threshold` (0.12),
  `min_authority` (0.0), `max_passages` (6), `passage_min_relevance` (0.05),
  `verification_enabled`; added `_env_float` + `RE_*` env wiring.
- **T42–T45 `ranking/` package**:
  - `authority.py` — `SourceAuthorityScorer`: deterministic domain/provider →
    tier + 0..1 score (peer-reviewed, official, educational, encyclopedia,
    reputable media, technical/personal blog, synthetic, unknown). Pure (no
    mutation).
  - `relevance.py` — `RelevanceScorer` interface; `HeuristicRelevanceScorer`
    (title-weighted topic-term coverage) default; `LLMRelevanceScorer` drop-in.
  - `passages.py` — `PassageSelector`: keeps top-N relevant passages, fail-open.
  - `ranker.py` — `DocumentRanker` (+ `build_ranker`): authority+relevance
    stamping, threshold/authority filtering, passage trimming; `RankOutcome`.
- **T46 wiring**: orchestrator runs the ranking gate between collection and
  processing. Rejected docs are counted (`session.rejected_documents`) and never
  reach processing or the knowledge graph. Evidence carries source relevance.
- Added `utils.domain_of` (stdlib urllib; requires a dot so offline `local://`
  locators resolve to no-domain → provider fallback).
- **Tests**: new `tests/test_ranking.py` (17 tests). **Full suite: 85 pass**
  (was 68). Verified live offline run: authority tiers assigned, relevance
  stamped, new fields serialized to session JSON.

### Design decisions
- Relevance is the rejection gate; **authority never rejects by default**
  (`min_authority=0.0`) — it feeds confidence. This keeps offline/`--no-llm`
  (synthetic sources, authority 0.2) fully working and tests deterministic.
- Ranker stamps scores on the **original** documents (kept in
  `raw_documents`/`sources` for the record) but processes **passage-trimmed
  copies** (via `dataclasses.replace`), so provenance is complete while
  extraction only sees high-value text.
- Heuristic relevance is the default even when an LLM is present — free,
  deterministic, reproducible. LLM relevance is an available, tested drop-in.

### Token usage changes
- Structural savings now in place (irrelevant docs dropped pre-extraction;
  accepted docs trimmed to relevant passages). Quantitative measurement deferred
  to T52 once verification/confidence stages are complete.

### Unresolved issues / blockers
- None. `claim_clusters` is populated by Phase C (next); currently empty.

### Remaining work
- Phase C (verification: clustering + verifier + semantic contradictions),
  Phase D (deterministic confidence), Phase E (report synthesis), Phase F (docs +
  token measurement + version bump). See `TASKS.md` T47–T52.

---

## Entry 1 — v0.3 planning + kickoff

**Date:** 2026-07-02

### Completed
- Reviewed the full existing architecture (all core subsystems) against the
  v0.3 objective. Confirmed no architectural redesign is required — the new
  capabilities fit as (a) a staged filtering gate between *collection* and
  *processing*, and (b) a verification + deterministic-confidence stage before
  *reasoning*. Everything sits behind the existing provider/model seams.
- Authored the v0.3 implementation plan in `TASKS.md` and created this log.

### Design decisions
- **Two new packages** keep responsibilities isolated:
  - `ranking/` — document ranking, source-authority scoring, relevance
    filtering, and passage selection (problems 1–5, 10). Deterministic by
    default; an LLM relevance scorer is an optional drop-in behind the same
    interface.
  - `verification/` — claim clustering and evidence verification (problems 6, 8).
- **Confidence** becomes a deterministic model in `reasoning/confidence.py`
  (problem 7): a pure function of measurable inputs (supporting sources,
  independent domains, source authority, claim agreement, contradiction count,
  extraction quality). Reproducible for identical inputs.
- **Domain-model changes are additive only** (new fields with defaults), so
  existing session JSON stays loadable and serialization stays compatible.
- **Filtering is fail-open at the passage level** (if nothing scores above the
  passage threshold, the whole document text is used) so a run never silently
  loses a genuinely relevant document to an over-eager heuristic.
- **Authority never gates by default** (`min_authority = 0.0`); authority feeds
  *confidence*, not rejection. Relevance is the rejection gate. This keeps the
  deterministic offline/`--no-llm` path (used by tests) fully functional.

### Architectural changes
- None to existing interfaces yet. New packages added; orchestrator gains a
  ranking stage between collection and processing.

### Token usage changes
- Expected reduction once ranking + passage selection are wired: only accepted
  documents, and only their relevant passages, reach LLM extraction. To be
  measured after the reasoning/verification stages land.

### Unresolved issues / blockers
- None.

### Remaining work
- See `TASKS.md` (T40–T52). Next: domain-model + config foundations, then the
  `ranking/` gate wired into the orchestrator with tests.
