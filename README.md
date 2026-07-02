# 🧠 Research Engine

> You give it a topic — or an actual question. It plans an investigation, skims
> search results like a picky librarian, downloads only what looks worth
> reading, distills it into claims, checks whether independent sources agree —
> and then it notices what it *still* doesn't know, goes looking for exactly
> that, measures whether it's actually learning anything, and stops with a
> reason on record. Then you get the answer, with citations, and the report
> that backs it up.

Research Engine is a **domain-agnostic autonomous research agent**. Point it at
*anything* — "CRISPR gene editing", "the history of the fork", "what are the
risks of quantum computing to cryptography?" — and it builds an internal
**knowledge model** out of verified claims: typed assertions extracted from
real sources, normalized, cross-checked for agreement, ranked by importance,
and scored with a confidence that comes with an explanation instead of a
shrug. The answer is synthesized from that model; the report is a rendering
of it.

**It is not a chatbot.** It will not tell you a joke, validate your feelings, or
help with your homework at 2am. It has exactly one job: research a topic and
leave a paper trail. Every statement in the report traces back through
finding → claim → evidence passage → document → source. It's the difference
between "trust me bro" and "here's my citation [S1]".

**Status:** **v0.5 — Autonomous Research Agent.** The engine no longer runs a
pipeline and calls it a day; it runs a *learning loop*. It keeps a single
research state, notices what it doesn't know (missing definitions, single-source
claims, contradictions), turns those gaps into new targeted searches, measures
how much every iteration actually taught it, and stops when it's confident,
out of gaps, or demonstrably no longer learning — with the reason on record.
The answer is the product; the report is a rendering of the knowledge model.
(The character-building journey here is in [The Backstory](#-the-backstory).)

---

## 🏃 Quick start

You need **Python 3.10+** and [**uv**](https://docs.astral.sh/uv/). The core
pipeline is pure standard library; the two dependencies (`openai`,
`python-dotenv`) just power the optional LLM and `.env` loading.

```bash
uv sync                                   # make the venv, install the two deps
uv run research-engine "Quantum Computing"
```

That's it. Go make tea. When you come back there's a report in `report/`.

Want it to actually *think* (LLM-powered planning, claim extraction,
equivalence judging, and answer synthesis)? Give it a key:

```bash
cp .env.example .env
# put OPENROUTER_API_KEY=sk-or-... inside
uv run research-engine "Quantum Computing" --verbose
```

No key, no network, or just feeling frugal? The engine still runs the entire
pipeline — deterministically:

```bash
uv run research-engine "Quantum Computing" --offline --no-llm   # zero cost, zero network
```

**No uv? No problem.** There's a zero-install escape hatch that degrades
gracefully if the optional packages are missing:

```bash
python3 main.py "Quantum Computing"
```

When it's done you get two files:

| File | What it is | Who it's for |
|------|------------|--------------|
| `report/<topic>_report.md` | The human-readable research report | You |
| `sessions/<topic>_session.json` | The full machine-readable session | Robots / debugging / regenerating the report |

---

## 🎬 The complete engine workflow

Here's the whole life of a research session, from "you hit enter" to "there's a
report." Each stage hands its output to the next and never reaches back —
subsystems only speak through the shared dataclasses in `domain/models.py`,
like polite coworkers who communicate exclusively via tickets.

```
     you type a topic — or a question
               │
               ▼
   ┌───────────────────────┐
   │  1. PLAN              │  Understand the input BEFORE searching: question or
   │  planner/             │  topic? what's the subject? Decompose into focused
   └──────────┬────────────┘  subquestions, each with targeted search queries.
              ▼
   ┌───────────────────────┐
   │  2. RETRIEVE          │  Run every subquestion's queries independently
   │  collection/          │  across Wikipedia + arXiv + DuckDuckGo. Merge,
   └──────────┬────────────┘  de-dupe. Results are METADATA ONLY — no downloads.
              ▼
   ┌───────────────────────┐
   │  3. EVALUATE          │  Judge each result by title/snippet/URL alone:
   │  ranking/             │  relevance, source authority, exclusion criteria.
   └──────────┬────────────┘  Reject the junk BEFORE spending bandwidth on it.
              ▼
   ┌───────────────────────┐
   │  4. DOWNLOAD+DISTILL  │  Fetch accepted candidates only. Split into
   │  collection/ ranking/ │  passages, keep the relevant ones as evidence.
   └──────────┬────────────┘  Whole documents never reach the LLM.
              ▼
   ┌───────────────────────┐
   │  5. CLAIMS            │  Extract TYPED claims from passages (facts,
   │  processing/          │  definitions, numbers, dates, limitations,
   │                       │  assumptions, methods, open questions) — never
   └──────────┬────────────┘  summaries. Merge duplicate wordings (normalize).
              ▼
   ┌───────────────────────┐
   │  6. VERIFY            │  Cluster equivalent claims across sources. Measure
   │  verification/        │  agreement. Detect contradictions. Flag anything
   └──────────┬────────────┘  only one source asserts. Stamp it all on the claim.
              ▼
   ┌───────────────────────┐
   │  7. BUILD KNOWLEDGE   │  Merge entity aliases, rebuild the claim-primary
   │  knowledge/           │  graph (typed edges: supports/contradicts/extends/
   │                       │  depends_on/defines), and stamp every claim's
   └──────────┬────────────┘  IMPORTANCE — not all information is equal.
              ▼
   ┌───────────────────────┐
   │  8. REASON + WONDER   │  Findings per subquestion + explained confidence
   │  reasoning/           │  (every iteration). Then curiosity kicks in: what's
   │                       │  never defined? single-sourced? contradicted? Each
   └──────────┬────────────┘  gap gets a suggested query and a priority.
              ▼
   ┌───────────────────────┐
   │  9. STOP OR LOOP?     │  Measure what this iteration actually taught the
   │  reasoning/           │  engine (novelty, knowledge gain). Stop when
   │                       │  confident, out of gaps, out of budget, or no
   └──────────┬────────────┘  longer learning — reason recorded. Else: the
              │               planner turns the best gaps into new searches,
              │ loop          GOTO 2.
              ▼ stop
   ┌───────────────────────┐
   │  10. ANSWER + REPORT  │  Synthesize the answer from the completed
   │  reasoning/ report/   │  knowledge model (citations included), then render
   │  storage/             │  the adaptive Markdown report — gaps, iteration
   └──────────┬────────────┘  history, and stop reason stated out loud.
              ▼
        a cited answer,
      and a clear conscience
```

**The golden rule:** every statement is traceable — answer/finding → claim →
evidence → document → source — and a report can always be regenerated from its
stored session snapshot. If the engine can't back it up, it says so explicitly
in *Limitations and Missing Evidence* instead of padding a template.

---

## 🚚 How a command actually moves through the code

You typed `uv run research-engine "Quantum Computing" --verbose`. Here's the
relay race that follows, baton-pass by baton-pass:

```
1.  cli.main(argv)                         cli.py
      └─ parses flags, catches errors, returns an exit code
         (2 = empty topic, 1 = something exploded, 0 = success)

2.  cli.run(argv)                          cli.py
      ├─ EngineConfig.from_env(...)        config.py
      │     loads .env → reads RE_*/OPENROUTER_* → applies CLI overrides
      ├─ build_search_provider(config)     providers/factory.py
      │     "offline"? → OfflineSearchProvider (deterministic, two-phase too)
      │     else       → CompositeSearchProvider([Wikipedia, arXiv, DuckDuckGo])
      └─ build_llm_provider(config)        providers/factory.py
            key present + enabled? → OpenRouterProvider   else → NullLLMProvider

3.  ResearchOrchestrator.run(request)      orchestrator/orchestrator.py
      │   (the conductor; the ONLY place that knows the running order)
      │
      ├─ planner.plan(request)             planner/planner.py    → ResearchPlan
      │     LLM plan as strict JSON, or the deterministic question-aware planner
      ├─ planner.tasks_for(plan)           taskgraph/graph.py    → ordered Task[]
      │
      ├─ ResearchState(...)                state/research_state.py
      │     the single source of truth the whole loop reads and writes
      │
      ├─ agent loop (until the stopping engine says stop):
      │     ├─ planner.next_search_tasks(state)   planner/planner.py
      │     │     iteration 1: the plan · later: open knowledge gaps,
      │     │     prioritized, deduped against the search history
      │     ├─ for each search task:
      │     │   ├─ retrieval.search(task)     collection/collector.py
      │     │   │     └─ provider.search_candidates()   ← metadata only
      │     │   ├─ evaluator.evaluate(...)    ranking/evaluator.py
      │     │   ├─ retrieval.download(accepted)
      │     │   │     └─ provider.fetch()     ← the ONLY place pages are fetched
      │     │   └─ processor.process(docs)    processing/processor.py
      │     ├─ normalizer.normalize(...)      processing/normalizer.py
      │     ├─ verifier.verify(...)           verification/verifier.py
      │     │     + LLM equivalence judge for borderline paraphrase pairs
      │     ├─ builder.build(...)             knowledge/builder.py
      │     ├─ importance.stamp(...)          reasoning/importance.py
      │     ├─ reasoner.analyze(...)          reasoning/analyzer.py
      │     ├─ curiosity.discover(...)        reasoning/curiosity.py → gaps
      │     ├─ gain.analyze(...)              reasoning/gain.py → IterationRecord
      │     └─ stopping.decide(state)         reasoning/stopping.py
      │
      ├─ answer_generator.generate(...)    reasoning/answer.py    → Answer
      ├─ report_generator.generate(…)      report/generator.py    → Markdown
      └─ storage.save_report() / save_session()   storage/storage.py

4.  cli._print_summary(session)            cli.py
      └─ prints the little status block you see at the end
```

If the LLM has a bad day at any step, nothing crashes — the affected step quietly
uses its deterministic fallback and the run finishes. The engine is aggressively
un-dramatic about failure.

---

## 🧩 The subsystems (who does what)

Each subsystem has exactly one job and no opinions about anyone else's.

| Subsystem | Package | Its one job |
|-----------|---------|-------------|
| Orchestrator | `orchestrator/` | Runs the agent loop; keeps calm when a source dies. |
| Research state | `state/` | The single source of truth during a run — everything reads from it, writes through it. |
| Planner | `planner/` | Understands the question; stays active all run, turning gaps into prioritized search tasks. |
| Task graph | `taskgraph/` | A DAG with dependency-ordered execution and cycle detection. |
| Retrieval | `collection/` | Executes search tasks; downloads *accepted* candidates only. Stateless. |
| Evaluation | `ranking/` | Judges candidates from metadata; authority scoring; passage selection. |
| Processing | `processing/` | Passages → typed claims → normalized canonical claims. |
| Verification | `verification/` | Clusters claims across sources (rarity-weighted + LLM equivalence judge); agreement, contradictions. |
| Knowledge | `knowledge/` | Builds the knowledge model: entity alias merging + the claim-primary typed graph. |
| Reasoning | `reasoning/` | Findings, confidence, claim importance, curiosity (gaps), information gain, stopping, the answer. |
| Report | `report/` | Renders the knowledge model as adaptive Markdown, citation chain intact. |
| Storage | `storage/` | Saves the report + session snapshot. |
| Providers | `providers/` | Pluggable two-phase search & LLM backends (the extension seam). |

<details>
<summary>Repository layout (click to expand)</summary>

```
core-engine/research_engine/
├── cli.py · api.py · service.py        user surfaces → service.run_research()
├── config.py                           every knob, one place (RE_* env vars)
├── domain/models.py                    the shared contract between subsystems
├── state/research_state.py             the run's single source of truth
├── orchestrator/orchestrator.py        the agent loop
├── planner/planner.py                  plan once, then next_search_tasks() forever
├── taskgraph/graph.py                  DAG + topological order
├── collection/collector.py             search tasks → candidates → documents
├── ranking/                            evaluator (metadata gate) · authority · passages
├── processing/                         extraction (typed claims) · normalizer · processor
├── verification/                       clustering (rarity-weighted) · equivalence (LLM judge) · verifier
├── knowledge/                          builder (alias merge) · graph (typed edges)
├── reasoning/                          analyzer · confidence · importance · gain ·
│                                       curiosity · stopping · answer
├── report/generator.py                 pure renderer
├── storage/storage.py                  report + session snapshot
└── providers/                          base interfaces · openrouter · offline ·
    └── sources/                        wikipedia · arxiv · duckduckgo · composite
tests/                                  168 network-free unittest tests
main.py                                 zero-install shim (python3 main.py "topic")
```

</details>

---

## 🔌 Providers (the "swap the engine while driving" part)

Data sources and language models live behind two interfaces — `SearchProvider`
and `LLMProvider` — so you can add new backends without touching the core engine.

- **Search (default):** a `CompositeSearchProvider` that fans out to real, no-key
  sources — **Wikipedia**, **arXiv**, and **DuckDuckGo** — merges and
  de-duplicates. Search is **two-phase**: `search_candidates()` returns titles,
  snippets, and URLs (cheap), and `fetch()` downloads one accepted result
  (expensive). Candidate evaluation sits between the phases, which is how the
  engine stopped downloading pages it was about to throw away. Each source is
  isolated, so one having a moment never sinks the run. `--offline` swaps in the
  deterministic `OfflineSearchProvider` (same two-phase interface, synthetic
  notes) for reproducible, network-free runs.
- **LLM (default, optional at runtime):** `OpenRouterProvider` speaks OpenRouter's
  OpenAI-compatible API and wakes up automatically when `OPENROUTER_API_KEY` is
  set. It powers the *semantic* steps only: research planning, typed claim
  extraction, the claim-equivalence judge (deciding whether two borderline
  claims assert the same fact — a genuinely semantic call no lexical threshold
  can make), and the phrasing of findings / the answer / hypotheses /
  summaries — always grounded in the material it is handed, never used as a
  knowledge source. Flaky model output is met with a light retry,
  code-fence-tolerant JSON parsing, and a deterministic fallback (the judge
  fails closed: unusable output means "not equivalent", never a fabricated
  merge). Everything measurable (relevance, authority, clustering, agreement,
  importance, gain, stopping, confidence) stays deterministic on principle.
  `--no-llm` forces the deterministic path on purpose.

> 💡 Model choice matters. The LLM is asked for strict JSON; a strong
> instruction-follower extracts cleanly, a weaker one triggers more fallbacks.
> Default is `openai/gpt-4o-mini`; set `OPENROUTER_MODEL` to whatever you like.

---

## ⚙️ Commands & configuration

```bash
uv run research-engine "<topic or question>" [options]
```

| Flag | What it does | Default |
|------|--------------|---------|
| `--max-subtopics N` | How many subquestions to investigate (1–7). | 6 |
| `--documents-per-query N` | Accepted candidates downloaded per subquestion. | 3 |
| `--max-iterations N` | Agent-loop search budget (iterations). | 3 |
| `--confidence-threshold X` | Stop looping once overall confidence ≥ X (0–1). | 0.7 |
| `--offline` | Deterministic offline source, no network (evidence is synthetic). | off |
| `--no-llm` | Deterministic planning/extraction/synthesis, skip the LLM. | off |
| `--output-dir DIR` | Where reports go. | `report` |
| `--sessions-dir DIR` | Where session snapshots go. | `sessions` |
| `-v`, `--verbose` | Debug logging (watch the sausage get made). | off |
| `-h`, `--help` | You know this one. | — |

**Config precedence** (each layer wins over the one before): built-in defaults →
`.env` file → environment variables → CLI flags. `config.py` is the single source
of truth. Engine knobs use `RE_*`; the LLM reads `OPENROUTER_API_KEY`,
`OPENROUTER_MODEL`, `OPENROUTER_BASE_URL`. See `.env.example` for the full list —
the claim-pipeline knobs (`RE_MAX_CANDIDATES_PER_QUERY`,
`RE_CANDIDATE_RELEVANCE_THRESHOLD`, …) plus the v0.5 agent knobs:
`RE_MIN_CLAIM_IMPORTANCE` (claims below this stay out of reasoning and the
report), `RE_MIN_ITERATION_GAIN` and `RE_MIN_CONFIDENCE_DELTA` (the "stop when
no longer learning" thresholds), `RE_MAX_SEARCH_TASKS_PER_ITERATION`, and
`RE_MAX_EQUIVALENCE_CHECKS` (borderline claim pairs the LLM judge reviews per
verification pass; `0` disables the judge).

---

## 📄 What's in a report

Sections **emerge from the evidence** — nothing renders just because a template
has a heading for it. A full report can contain: Executive Summary · **Answer**
(a *Direct Answer* for questions, the core understanding for topics — with the
claims it rests on, the reasoning, and what remains uncertain) · Research Plan ·
Key Findings · Verified Claims (**ranked by importance**, top 25 in print, the
rest preserved in the session snapshot) · Contradictions · Uncertainty and
Confidence (score + factor table + plain-language explanation) · **Knowledge
Gaps** (what the agent noticed it didn't know — split into *investigated* and
*still open*) · Limitations and Missing Evidence · Future Research ·
Recommendations · Appendix (a **Research Iterations** table showing per-pass
novelty, knowledge gain, and confidence; the recorded **stop reason**;
retrieval statistics; sources; session metadata).

The answer cites claims, findings cite claims (`claim-3`), claims cite their
evidence passages and sources (`[evidence: ev-7 → S2]`), and sources carry
their authority tier. Follow the breadcrumbs all the way down; they lead
somewhere real. And when the engine *couldn't* answer something, the report
says exactly that instead of mumbling.

---

## 🌐 HTTP API (optional)

Prefer talking to the engine over HTTP? There's a thin FastAPI wrapper
(`research_engine/api.py`) that runs a session and hands you back the whole thing
as JSON. It's an **optional extra** so the core install stays lean:

```bash
uv sync --extra api            # installs fastapi + uvicorn
uv run research-engine-api     # serves on http://127.0.0.1:8000 (RE_API_HOST/RE_API_PORT to change)
```

Endpoints:

| Method & path | What it does |
|---------------|--------------|
| `GET /health` | Liveness + version. |
| `POST /research` | Runs a full session, returns the serialized session as JSON. |
| `GET /docs` | Auto-generated Swagger UI (courtesy of FastAPI). |

```bash
curl -X POST http://127.0.0.1:8000/research \
  -H "Content-Type: application/json" \
  -d '{"topic": "Quantum Computing", "max_subtopics": 4}'
```

Request body: `topic` (required), plus optional `max_subtopics` (1–7),
`documents_per_query`, `offline`, and `no_llm`. The response is the complete
session — the plan, the candidate audit trail, evidence, verified claims, the
evidence graph, findings, hypotheses, confidence, and the report (including its
Markdown). Empty/invalid input returns `422`; an empty topic that slips through
returns `400`. The endpoint is synchronous on purpose (FastAPI runs it in a
worker thread), because a real run is blocking and can take a minute or two.

It reuses the exact same engine as the CLI (via `service.run_research`), so
whatever the CLI produces, the API produces — just JSON-shaped.

## 🧪 Running the tests

```bash
uv run python -m unittest discover -s tests
```

Stdlib `unittest`, no external runner, **168 tests**, all network-free (the
source providers are tested with injected fake fetchers, so the suite never
actually hits Wikipedia). Covers every subsystem plus full offline end-to-end
runs — including determinism across runs, gap-driven iteration, explicit stop
reasons, and the agent loop's budget.

---

## 🙃 Known limitations (told honestly)

The evidence is real, cited, and now cross-checked — but let's not oversell it:

- **"Verification" means cross-source corroboration,** not fact-checking against
  ground truth. If three websites confidently repeat the same mistake, the
  engine will report a well-corroborated mistake (with citations!).
- **Corroboration is conservative by design.** Auto-merge only accepts
  near-identical wordings (a false merge *fabricates* corroboration, which is
  worse than a missed one); the LLM judge reviews the borderline band and
  fails closed. Real sources rarely assert the same sentence-grain fact in
  clean paraphrase, so most claims will honestly report `single_source`.
  Sub-sentence fact alignment is future work.
- **Candidate relevance is judged from titles and snippets.** That's the point
  (don't download junk), but a great page with a terrible title can get
  rejected at the door. The thresholds are tunable.
- **Contradiction detection is a negation heuristic.** It catches "X is
  effective" vs "X is not effective." It does not catch subtle intellectual
  disagreement. A semantic detector can drop in behind the same interface.
- **Extraction quality is model-dependent.** A weak strict-JSON follower
  triggers the heuristic fallback (one claim per sentence — noisier), which
  the importance filter then has to absorb. A stronger `OPENROUTER_MODEL` is
  the cheapest quality upgrade available.
- **DuckDuckGo scraping is held together with optimism.** No official API; the
  endpoint and markup can shift. Best-effort, fails closed. Wikipedia can also
  rate-limit (HTTP 429) under multi-iteration runs; retry/backoff is queued
  for the v0.6 networking pass.
- **Tokens cost money.** A live multi-iteration run spends LLM calls on
  planning, per-document extraction, borderline-pair judging, per-iteration
  synthesis, and the final answer (a measured 3-iteration run: ~53 calls).
  `--offline` and `--no-llm` are the free tier of your own making.

These all live behind interfaces, so future-you can upgrade them without a
rewrite. See *Technical Debt* in `TASKS.md`.

---

## 📜 The backstory

**v0.1** proved the entire pipeline worked end to end — with one asterisk: the
"evidence" was generated by an offline heuristic. Beautifully structured,
impeccably cited, and completely made up.

**v0.2** swapped the plastic food for the real thing: real sources (Wikipedia +
arXiv + DuckDuckGo) and a real LLM pipeline. Because everything talks through
interfaces and shared models, it was a transplant, not an autopsy.

**v0.3** made the engine picky: relevance filtering, source authority scoring,
passage selection, claim clustering across sources, and deterministic
confidence. Evidence quality went from "everything counts" to "prove it."

**v0.4** made claims the star of the show. Documents are just containers.
The engine plans before it searches, judges results before it downloads them,
extracts typed claims instead of summaries, verifies claims against each other,
reasons over an evidence graph, answers questions directly, explains its
confidence factor by factor, and loops back for more evidence when it isn't
confident enough. The report finally has the nerve to leave sections out.

**v0.5 (now)** turned the pipeline into an agent. One `ResearchState` holds
everything; the planner never clocks out; curiosity converts what's missing
(undefined entities, single-source claims, contradictions, low-authority
evidence) into the next iteration's searches; every claim gets an importance
score so trivia stops crowding out concepts; every iteration gets a
knowledge-gain score so the engine can tell when it's learning versus
spinning; and a stopping engine ends the run with an explicit, recorded
reason. Live-run diagnosis also fixed verification: rarity-weighted claim
clustering plus an LLM equivalence judge for the borderline pairs plain
lexical similarity can't decide — the difference between corroborating ~0% of
claims and actually noticing when independent sources agree.

---

## 🗺️ Source of truth

This repo governs itself with documents. `PROJECT.md` (the vision), `ARCHITECTURE.md`
(the design), `OBJECTIVE.md` (the current milestone — owner-owned), and `TASKS.md`
(engineer-owned implementation status). When in doubt, those win over this README.
This README is just the one that's allowed to have fun.
