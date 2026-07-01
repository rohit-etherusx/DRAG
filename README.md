# 🧠 Research Engine

> You give it a topic. It goes off, reads the internet, takes notes like an
> over-caffeinated grad student, argues with itself about what's important, and
> hands you a cited report. Then it goes back to sleep.

Research Engine is a **domain-agnostic autonomous research system**. Point it at
*anything* — "CRISPR gene editing", "the history of the fork", "why is the sky
blue and who decided that" — and it plans an investigation, gathers real
evidence from multiple sources, organizes it into a knowledge graph, reasons over
it to produce findings and testable hypotheses (with confidence levels, because
it has the decency to admit when it's guessing), and writes you a structured
Markdown report.

**It is not a chatbot.** It will not tell you a joke, validate your feelings, or
help with your homework at 2am. It has exactly one job: research a topic and
leave a paper trail. Every claim links back to a real source. It's the difference
between "trust me bro" and "here's my citation [S1]".

**Status:** **v0.2 — Grounded Research.** It reads real web pages now. In v0.1 it
made things up in a very organized, well-cited, entirely fictional way. We fixed
that. (More on that character-building era in [The Backstory](#-the-backstory).)

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

Want it to actually *think* (LLM-powered analysis), not just gather? Give it a key:

```bash
cp .env.example .env
# put OPENROUTER_API_KEY=sk-or-... inside
uv run research-engine "Quantum Computing" --verbose
```

No key, no network, or just feeling frugal? The engine still runs — deterministically:

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

Here's the whole life of a research session, from "you hit enter" to "there's a report." Each stage hands its output to the next and never reaches back — subsystems only speak through the shared dataclasses in `domain/models.py`, like polite coworkers who communicate exclusively via tickets.

```
        you type a topic
               │
               ▼
   ┌───────────────────────┐
   │  1. PLAN              │  Break the topic into research angles
   │  planner/            │  ("overview of X", "history of X", "challenges of X"…)
   └──────────┬────────────┘  + one converging synthesis task
              ▼
   ┌───────────────────────┐
   │  2. TASK GRAPH       │  Angles become a DAG. Sort by dependencies.
   │  taskgraph/          │  Collect tasks first; synthesis waits for all of them.
   └──────────┬────────────┘  (Yes, it detects cycles. No, it won't loop forever.)
              ▼
   ┌───────────────────────┐
   │  3. COLLECT          │  For each angle, fan out to REAL sources:
   │  collection/         │     Wikipedia + arXiv + DuckDuckGo
   │  providers/sources/  │  Merge, de-dupe, stamp provenance.
   └──────────┬────────────┘  One source dies? Shrug, carry on with the rest.
              ▼
   ┌───────────────────────┐
   │  4. PROCESS          │  LLM reads the real text and extracts:
   │  processing/         │     • self-contained claims
   │                      │     • the entities they mention
   └──────────┬────────────┘     • relationships between those entities
              ▼                 (No LLM? Deterministic sentence-splitting kicks in.)
   ┌───────────────────────┐
   │  5. KNOWLEDGE GRAPH  │  Entities become nodes. Co-occurrence makes edges;
   │  knowledge/          │  LLM-found relationships upgrade them to typed,
   └──────────┬────────────┘  directed relations ("Cas9 —cuts→ DNA").
              ▼
   ┌───────────────────────┐
   │  6. REASON           │  Synthesize a finding per angle, propose testable
   │  reasoning/          │  hypotheses, list open questions, score confidence,
   └──────────┬────────────┘  write the executive summary. (Each step: LLM, or fallback.)
              ▼
   ┌───────────────────────┐
   │  7. REPORT           │  Render everything to Markdown, keeping every
   │  report/             │  finding → evidence → source citation link intact.
   └──────────┬────────────┘
              ▼
   ┌───────────────────────┐
   │  8. PERSIST          │  Write report/<topic>_report.md and the full
   │  storage/            │  sessions/<topic>_session.json snapshot.
   └──────────┬────────────┘
              ▼
        a cited report,
      and a clear conscience
```

**The golden rule:** every meaningful conclusion is traceable to collected
evidence, and a report can always be regenerated from its stored session
snapshot. If the engine can't back it up, it doesn't say it (or it files it under
"open questions" and moves on, like an honest person).

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
      │     (--offline and --no-llm sneak in here as config values)
      ├─ build_search_provider(config)     providers/factory.py
      │     "offline"? → OfflineSearchProvider (the deterministic stub)
      │     else       → CompositeSearchProvider([Wikipedia, arXiv, DuckDuckGo])
      └─ build_llm_provider(config)        providers/factory.py
            key present + enabled? → OpenRouterProvider   else → NullLLMProvider

3.  ResearchOrchestrator.run(request)      orchestrator/orchestrator.py
      │   (the conductor; the ONLY place that knows the running order)
      │
      ├─ planner.plan(request)             planner/planner.py     → a TaskGraph
      ├─ graph.topological_order()         taskgraph/graph.py     → ordered Task[]
      │
      ├─ for each COLLECT task:
      │     ├─ collector.collect(task)     collection/collector.py
      │     │     └─ provider.search()     providers/sources/composite.py
      │     │           ├─ wikipedia.py    (MediaWiki API → clean extracts)
      │     │           ├─ arxiv.py        (Atom API → abstracts)
      │     │           └─ duckduckgo.py   (lite endpoint, POST → page text)
      │     └─ processor.process(docs)     processing/processor.py
      │           └─ extractor.extract()   processing/extraction.py
      │                 LLMClaimExtractor → OpenRouter → JSON claims/entities/rels
      │                 (unusable JSON? retry, then fall back to heuristics)
      │
      ├─ knowledge_graph.build(evidence)                 knowledge/graph.py
      │  knowledge_graph.add_extracted_relationships(…)  (typed edges)
      │
      ├─ reasoner.analyze(…)               reasoning/analyzer.py
      │     findings + hypotheses + open questions + confidence + summary
      │     (every LLM call: light retry → deterministic fallback)
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
| Orchestrator | `orchestrator/` | Runs the show; keeps calm when a source dies. |
| Planner | `planner/` | Turns a topic into research angles + a synthesis task. |
| Task graph | `taskgraph/` | A DAG with dependency-ordered execution and cycle detection. |
| Collection | `collection/` | Fetches raw documents via a `SearchProvider`. No thinking. |
| Processing | `processing/` | Extracts claims, entities, relationships; de-dupes; flags contradictions. |
| Knowledge graph | `knowledge/` | Entities + (typed) relationships. The session's memory. |
| Reasoning | `reasoning/` | Findings, hypotheses, confidence, gaps, summary. |
| Report | `report/` | Renders the Markdown, citations intact. |
| Storage | `storage/` | Saves the report + session snapshot. |
| Providers | `providers/` | Pluggable search & LLM backends (the extension seam). |

---

## 🔌 Providers (the "swap the engine while driving" part)

Data sources and language models live behind two interfaces — `SearchProvider`
and `LLMProvider` — so you can add new backends without touching the core engine.
This is the whole reason v0.1 → v0.2 was a swap and not a rewrite.

- **Search (default):** a `CompositeSearchProvider` that fans out to real, no-key
  sources — **Wikipedia** (clean article extracts), **arXiv** (paper abstracts),
  and **DuckDuckGo** (open-web page text) — then merges and de-duplicates. Each
  source is isolated, so one having a moment never sinks the run. `--offline`
  swaps in the deterministic `OfflineSearchProvider` stub for reproducible,
  network-free runs (and for the test suite, which prefers not to phone home).
- **LLM (default, optional at runtime):** `OpenRouterProvider` speaks OpenRouter's
  OpenAI-compatible API and wakes up automatically when `OPENROUTER_API_KEY` is
  set. It powers the reasoning pipeline: **claim, entity, and relationship
  extraction** plus **finding, hypothesis, and summary synthesis**. Flaky model
  output is met with a light retry, code-fence-tolerant JSON parsing, and a
  deterministic fallback — so it never *fails*, it just occasionally shrugs and
  does it the boring way. `--no-llm` forces the boring way on purpose.

> 💡 Model choice matters. The LLM is asked for strict JSON; a strong
> instruction-follower extracts cleanly, a weaker one triggers more fallbacks.
> Default is `openai/gpt-4o-mini`; set `OPENROUTER_MODEL` to whatever you like.

---

## ⚙️ Commands & configuration

```bash
uv run research-engine "<topic>" [options]
```

| Flag | What it does | Default |
|------|--------------|---------|
| `--max-subtopics N` | How many research angles to chase (1–7). | 6 |
| `--documents-per-query N` | Docs gathered per angle (per source share). | 3 |
| `--offline` | Deterministic offline source, no network (evidence is synthetic). | off |
| `--no-llm` | Deterministic extraction/synthesis, skip the LLM. | off |
| `--output-dir DIR` | Where reports go. | `report` |
| `--sessions-dir DIR` | Where session snapshots go. | `sessions` |
| `-v`, `--verbose` | Debug logging (watch the sausage get made). | off |
| `-h`, `--help` | You know this one. | — |

**Config precedence** (each layer wins over the one before): built-in defaults →
`.env` file → environment variables → CLI flags. `config.py` is the single source
of truth. Engine knobs use `RE_*` (`RE_MAX_SUBTOPICS`, `RE_DOCUMENTS_PER_QUERY`,
`RE_OUTPUT_DIR`, `RE_LLM_ENABLED`, `RE_LLM_MODEL`, `RE_LOG_LEVEL`); the LLM reads
`OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `OPENROUTER_BASE_URL`. See `.env.example`.

---

## 📄 What's in a report

Every report contains, in order: Executive Summary · Research Objectives · Key
Findings · Supporting Evidence · Extracted Entities · Relationships Between
Entities · Generated Hypotheses · Confidence Assessment · Contradictions · Open
Questions · Suggestions for Further Investigation · Citations & References ·
Session Metadata.

Findings and hypotheses carry `[S1, S2]`-style citations that point at the
Citations section, which points at real URLs. Follow the breadcrumbs all the way
down; they lead somewhere real now.

---

## 🧪 Running the tests

```bash
uv run python -m unittest discover -s tests
```

Stdlib `unittest`, no external runner, **64 tests**, all network-free (the source
providers are tested with injected fake fetchers, so the suite never actually
hits Wikipedia). Covers every subsystem plus a full offline end-to-end run.

---

## 🙃 Known limitations (told honestly)

The evidence is real and cited now, but let's not oversell it:

- **arXiv has a loose interpretation of "relevant."** Its keyword search
  occasionally returns a paper that's *technically* about your topic the way a
  fortune cookie is *technically* about your future.
- **DuckDuckGo scraping is held together with optimism.** There's no official
  API, so the endpoint and markup can shift. It's best-effort and fails closed.
- **No cross-source fact-checking yet.** Claims are cited but not yet
  cross-verified for agreement between sources — confidence reflects *how many*
  sources showed up, not whether they actually agree. (That's literally the
  headline feature of v0.3.)
- **Contradiction detection is a simple negation heuristic.** It catches "X is
  true" vs "X is not true." It does not catch subtle intellectual disagreement.
- **Tokens cost money.** A live run is ~15–40k output tokens. `--offline` and
  `--no-llm` are the free-tier of your own making.

These all live behind interfaces, so future-you can upgrade them without a
rewrite. See *Technical Debt* and *Next Recommended Objective* in `TASKS.md`.

---

## 📜 The backstory

**v0.1** proved the entire pipeline worked end to end — planning, task graph,
collection, processing, knowledge graph, reasoning, report — with one asterisk:
the "evidence" was generated by an offline heuristic. Beautifully structured,
impeccably cited, and completely made up. It was a research engine that had never
done any research, like a très fancy restaurant with plastic food in the window.

**v0.2** kept every subsystem and swapped the plastic food for the real thing:
real sources (Wikipedia + arXiv + DuckDuckGo) and a real LLM reasoning pipeline
(claims, entities, relationships, findings, hypotheses). Because everything talks
through interfaces and shared models, it was a transplant, not an autopsy.

**v0.3 (next):** cross-source verification (make confidence mean something),
an optional research-grade keyed search provider, and a relevance filter so
arXiv stops bringing tangents to the party.

---

## 🗺️ Source of truth

This repo governs itself with documents. `PROJECT.md` (the vision), `ARCHITECTURE.md`
(the design), `OBJECTIVE.md` (the current milestone — owner-owned), and `TASKS.md`
(engineer-owned implementation status). When in doubt, those win over this README.
This README is just the one that's allowed to have fun.
