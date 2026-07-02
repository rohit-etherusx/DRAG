# development-log.md

Running progress log for **Research Engine v0.3 — Evidence Quality, Verification,
and Research Reasoning** (see `OBJECTIVE.md`).

Per `OBJECTIVE.md`, this is the single running progress log. `TASKS.md` holds the
implementation plan / task board; this file records what was actually done, why,
and what remains. Newest entries first.

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
