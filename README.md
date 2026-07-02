# 🧠 Research Engine

> You give it a topic — or an actual question. It plans an investigation, skims
> search results like a picky librarian, downloads only what looks worth
> reading, distills it into claims, checks whether independent sources agree,
> argues with itself about what's solid, and hands you a cited report. Then it
> goes back to sleep.

Research Engine is a **domain-agnostic autonomous research system**. Point it at
*anything* — "CRISPR gene editing", "the history of the fork", "what are the
risks of quantum computing to cryptography?" — and it produces a structured
Markdown report built from **verified claims**: typed assertions extracted from
real sources, normalized, cross-checked for agreement, and scored with a
confidence that comes with an explanation instead of a shrug.

**It is not a chatbot.** It will not tell you a joke, validate your feelings, or
help with your homework at 2am. It has exactly one job: research a topic and
leave a paper trail. Every statement in the report traces back through
finding → claim → evidence passage → document → source. It's the difference
between "trust me bro" and "here's my citation [S1]".

**Status:** **v0.4 — Claim-Centric Research.** Documents are no longer the unit
of reasoning; claims are. The engine now evaluates search results *before*
downloading them, reasons only over verified claims, answers questions directly
when you ask one, and loops back for more evidence when confidence is low.
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

Want it to actually *think* (LLM-powered planning, extraction, and synthesis)?
Give it a key:

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
   │  7. EVIDENCE GRAPH    │  Claims become the primary nodes; evidence,
   │  knowledge/           │  documents, entities orbit them. Typed edges:
   └──────────┬────────────┘  supports/contradicts/extends/depends_on/defines.
              ▼
   ┌───────────────────────┐
   │  8. REASON            │  Over verified claims ONLY: findings per
   │  reasoning/           │  subquestion, a direct answer if you asked a
   │                       │  question, patterns, gaps, hypotheses, and
   └──────────┬────────────┘  deterministic confidence WITH an explanation.
              ▼
        confidence below threshold and gaps to fill?
              │ yes → generate follow-up searches, GOTO 2 (the research loop)
              ▼ no
   ┌───────────────────────┐
   │  9. REPORT + PERSIST  │  Adaptive Markdown report — sections appear only
   │  report/ storage/     │  when evidence supports them; missing evidence is
   └──────────┬────────────┘  stated out loud. Save report + session snapshot.
              ▼
        a cited report,
      and a clear conscience
```

**The golden rule:** every report statement is traceable — finding → claim →
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
      ├─ research loop (until confident, out of gaps, or out of budget):
      │     for each (weak) subquestion:
      │       ├─ retrieval.retrieve(sq)      collection/collector.py
      │       │     └─ provider.search_candidates()   ← metadata only
      │       ├─ evaluator.evaluate(...)     ranking/evaluator.py
      │       │     relevance + authority + exclusions, judged from snippets
      │       ├─ retrieval.download(accepted)
      │       │     └─ provider.fetch()      ← the ONLY place pages are fetched
      │       └─ processor.process(docs)     processing/processor.py
      │             ├─ PassageSelector       ranking/passages.py
      │             └─ ClaimExtractor        processing/extraction.py (typed JSON)
      │     ├─ normalizer.normalize(...)     processing/normalizer.py
      │     ├─ verifier.verify(...)          verification/verifier.py
      │     ├─ EvidenceGraph.build(...)      knowledge/graph.py
      │     └─ reasoner.analyze(...)         reasoning/analyzer.py
      │           findings, direct answer, patterns, gaps, hypotheses,
      │           ConfidenceModel.report(...)   reasoning/confidence.py
      │
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
| Orchestrator | `orchestrator/` | Runs the show + the research loop; keeps calm when a source dies. |
| Planner | `planner/` | Understands the question; produces the structured research plan. |
| Task graph | `taskgraph/` | A DAG with dependency-ordered execution and cycle detection. |
| Retrieval | `collection/` | Per-subquestion searches; downloads *accepted* candidates only. |
| Evaluation | `ranking/` | Judges candidates from metadata; authority scoring; passage selection. |
| Processing | `processing/` | Passages → typed claims → normalized canonical claims. |
| Verification | `verification/` | Clusters claims across sources; agreement, contradictions, unsupported. |
| Evidence graph | `knowledge/` | Claim-primary graph with typed edges. The session's memory. |
| Reasoning | `reasoning/` | Findings, direct answers, patterns, gaps, hypotheses, explained confidence. |
| Report | `report/` | Renders adaptive Markdown, citation chain intact. |
| Storage | `storage/` | Saves the report + session snapshot. |
| Providers | `providers/` | Pluggable two-phase search & LLM backends (the extension seam). |

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
  extraction, and the phrasing of findings / direct answers / hypotheses /
  summaries — always grounded in the material it is handed. Flaky model output
  is met with a light retry, code-fence-tolerant JSON parsing, and a
  deterministic fallback. Everything measurable (relevance, authority,
  clustering, agreement, confidence) stays deterministic on principle.
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
| `--max-iterations N` | Research-loop search budget (retrieval passes). | 2 |
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
`OPENROUTER_MODEL`, `OPENROUTER_BASE_URL`. See `.env.example` for the full list,
including the claim-pipeline knobs (`RE_MAX_CANDIDATES_PER_QUERY`,
`RE_CANDIDATE_RELEVANCE_THRESHOLD`, `RE_CONFIDENCE_THRESHOLD`,
`RE_MAX_ITERATIONS`, …).

---

## 📄 What's in a report

Sections **emerge from the evidence** — nothing renders just because a template
has a heading for it. A full report can contain: Executive Summary · Direct
Answer (when you asked a question) · Research Plan · Key Findings ·
Verified Claims · Contradictions · Uncertainty and Confidence (score + factor
table + plain-language explanation) · Limitations and Missing Evidence · Future
Research · Recommendations · Appendix (retrieval statistics, sources, session
metadata).

Findings cite claims (`claim-3`), claims cite their evidence passages and
sources (`[evidence: ev-7 → S2]`), and sources carry their authority tier.
Follow the breadcrumbs all the way down; they lead somewhere real. And when the
engine *couldn't* answer something, the report says exactly that instead of
mumbling.

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

Stdlib `unittest`, no external runner, **125 tests**, all network-free (the
source providers are tested with injected fake fetchers, so the suite never
actually hits Wikipedia). Covers every subsystem plus full offline end-to-end
runs — including determinism across runs and the research loop's budget.

---

## 🙃 Known limitations (told honestly)

The evidence is real, cited, and now cross-checked — but let's not oversell it:

- **"Verification" means cross-source corroboration,** not fact-checking against
  ground truth. If three websites confidently repeat the same mistake, the
  engine will report a well-corroborated mistake (with citations!).
- **Candidate relevance is judged from titles and snippets.** That's the point
  (don't download junk), but a great page with a terrible title can get
  rejected at the door. The thresholds are tunable.
- **Contradiction detection is a negation heuristic.** It catches "X is
  effective" vs "X is not effective." It does not catch subtle intellectual
  disagreement. A semantic detector can drop in behind the same interface.
- **DuckDuckGo scraping is held together with optimism.** No official API; the
  endpoint and markup can shift. Best-effort, fails closed.
- **Tokens cost money.** A live LLM run spends tokens on planning, extraction,
  and synthesis (though far fewer than before — whole documents no longer get
  shipped to the model). `--offline` and `--no-llm` are the free tier of your
  own making.

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

**v0.4 (now)** made claims the star of the show. Documents are just containers.
The engine plans before it searches, judges results before it downloads them,
extracts typed claims instead of summaries, verifies claims against each other,
reasons over an evidence graph, answers questions directly, explains its
confidence factor by factor, and loops back for more evidence when it isn't
confident enough. The report finally has the nerve to leave sections out.

---

## 🗺️ Source of truth

This repo governs itself with documents. `PROJECT.md` (the vision), `ARCHITECTURE.md`
(the design), `OBJECTIVE.md` (the current milestone — owner-owned), and `TASKS.md`
(engineer-owned implementation status). When in doubt, those win over this README.
This README is just the one that's allowed to have fun.
