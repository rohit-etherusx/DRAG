# Research Engine

A domain-agnostic autonomous research system. Given a topic, it plans and
executes a multi-step investigation, gathers information, organizes it into
structured evidence and a knowledge graph, reasons over that evidence to produce
findings and hypotheses with confidence estimates, and generates a structured
Markdown research report.

This repository is the single source of truth. See `PROJECT.md` (vision),
`ARCHITECTURE.md` (design), `OBJECTIVE.md` (current milestone), and `TASKS.md`
(implementation status).

**Status:** Research Engine **v0.1** — a complete, working end-to-end pipeline
(the MVP vertical slice). Every major subsystem exists in a minimal but working
form.

---

## Quick start

The project uses [uv](https://docs.astral.sh/uv/) for dependency management.
The **core pipeline uses only the Python standard library** (Python 3.10+); the
declared dependencies (`openai`, `python-dotenv`) support the optional
OpenRouter LLM provider and `.env` loading.

```bash
# From the repository root:
uv sync                                  # create the venv and install deps
uv run research-engine "Quantum Computing"

# Options:
uv run research-engine "Climate Change" --max-subtopics 5 --documents-per-query 4
uv run research-engine "Photosynthesis" --no-llm   # deterministic synthesis only
uv run research-engine "Black Holes" --verbose     # debug logging
```

The report is written to `report/<topic>_report.md` and a full machine-readable
session snapshot to `sessions/<topic>_session.json`.

Zero-install entry point (no dependencies required; the LLM and `.env` loading
are simply skipped if their optional packages are absent):

```bash
python3 main.py "Quantum Computing"
```

## Running the tests

```bash
uv run python -m unittest discover -s tests
```

The suite (stdlib `unittest`, no external runner) covers each subsystem plus a
full offline end-to-end run.

---

## How it works

The engine is a set of loosely-coupled subsystems that communicate only through
the shared domain models in `research_engine.domain.models`. The orchestrator
drives the lifecycle:

```
topic → plan → task graph → collect → process → knowledge graph
      → reason → report → persist
```

| Subsystem | Package | Responsibility |
|-----------|---------|----------------|
| Orchestrator | `orchestrator/` | Coordinates the lifecycle; handles task failures. |
| Planner | `planner/` | Turns the topic into research angles + a synthesis task. |
| Task graph | `taskgraph/` | Directed acyclic graph with dependency-ordered execution. |
| Collection | `collection/` | Acquires raw documents via a `SearchProvider`. |
| Processing | `processing/` | Extracts/normalizes evidence, entities, contradictions. |
| Knowledge graph | `knowledge/` | Entities + co-occurrence relationships. |
| Reasoning | `reasoning/` | Findings, hypotheses, confidence, gaps, summary. |
| Report | `report/` | Renders the Markdown research report. |
| Storage | `storage/` | Persists report + session snapshot. |
| Providers | `providers/` | Pluggable search and LLM backends. |

Every finding and hypothesis links back to the evidence and sources that support
it, and every report is reproducible from its stored session snapshot.

## Providers (the extension seam)

Data sources and language models sit behind interfaces (`SearchProvider`,
`LLMProvider`), so new backends are added without touching the core engine.

- **Search (default):** `OfflineSearchProvider` — a deterministic *local
  knowledge source*. It makes the engine runnable and reproducible anywhere with
  zero setup. It is a placeholder for real web/API providers and is clearly
  attributed as such in every report.
- **LLM (default, optional at runtime):** `OpenRouterProvider` uses OpenRouter's
  OpenAI-compatible API and activates automatically when an `OPENROUTER_API_KEY`
  is present. It is used only to enrich the executive summary; without a key a
  deterministic summary is produced (the engine never fails for lack of an LLM).
  Copy `.env.example` to `.env` and set `OPENROUTER_API_KEY` (optionally
  `OPENROUTER_MODEL`, default `openai/gpt-4o-mini`).

## Configuration

`config.py` is the single source of runtime settings. It loads a local `.env`
(git-ignored), then environment variables, then per-run CLI flags — each layer
overriding the previous. Engine settings use `RE_*` variables (e.g.
`RE_MAX_SUBTOPICS`, `RE_DOCUMENTS_PER_QUERY`, `RE_OUTPUT_DIR`, `RE_LLM_ENABLED`,
`RE_LLM_MODEL`, `RE_LOG_LEVEL`); the LLM provider also reads `OPENROUTER_API_KEY`,
`OPENROUTER_MODEL`, and `OPENROUTER_BASE_URL`. See `.env.example`.

## Known limitations (v0.1)

The offline search provider generates heuristic, self-referential evidence to
keep the pipeline reproducible offline; it is not externally-verified signal.
Entity extraction and contradiction detection are deliberately simple heuristics.
These are isolated behind interfaces so a future objective can replace them —
see the *Technical Debt* and *Next Recommended Objective* sections of `TASKS.md`.
