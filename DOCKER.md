# Running the Research Engine in Docker

One image bundles the whole thing: the engine, the FastAPI backend, and the
built React web app — all served from a single port (**8000** by default).

## Build

```bash
docker build -t research-engine .
```

No build arguments are required. The build has two stages (a Node stage builds
the web app, a Python/uv stage installs the engine and copies the build in), so
the final image only carries the Python runtime + the static `ui/dist` — not
Node or `node_modules`.

## Run (the short version)

```bash
docker run --rm -p 8000:8000 research-engine
```

Then open **http://localhost:8000** — that's the web app. The same port also
serves the API (`/health`, `/research`, `/research/stream`, `/docs`).

- Works on the **default port 8000** with no env vars at all.
- Foreground (no `-d`) → **engine logs stream live to your terminal**
  (planning, each iteration, claims, corroboration, confidence, stop reason).
  Press `Ctrl+C` to stop.
- Without an API key it runs fully, using **deterministic synthesis** as a
  fallback. Add a key (below) to enable LLM-powered planning/extraction/answers.

## Which interface runs?

The image ships **all three** interfaces; the default is the web GUI. Pick one
by overriding the command:

| Interface | Command | Notes |
|-----------|---------|-------|
| **Web GUI + API** (default) | `docker run --rm -p 8000:8000 research-engine` | Serves the web app + API on port 8000. Needs `-p`. |
| **Live TUI** (animated dashboard) | `docker run --rm -it -v "$(pwd)/report:/app/report" research-engine research-engine-tui "Quantum Computing"` | Needs **`-it`** (an interactive terminal) or it falls back to the plain CLI. No `-p` — it's not a server. |
| **Plain CLI** | `docker run --rm -v "$(pwd)/report:/app/report" research-engine research-engine "Quantum Computing"` | One-shot; prints a summary and writes the report. |

The TUI and CLI take the same flags as usual (`--offline`, `--no-llm`,
`--max-iterations N`, …) and add an LLM with `--env-file .env` or
`-e OPENROUTER_API_KEY=…` just like the server. Mount `-v …:/app/report` to keep
the report file, since these modes don't leave a server running to browse.

## What you pass in

### Ports

| Flag | Effect |
|------|--------|
| `-p 8000:8000` | Default. Host 8000 → container 8000. |
| `-p 9000:8000` | Serve on host **9000** (container stays 8000). |
| `-e RE_API_PORT=8080 -p 8080:8080` | Change the port *inside* the container too. |

The container already binds `0.0.0.0` (via `RE_API_HOST`), so the port is
reachable from the host — you don't need to set that yourself.

### Environment variables

Pass with `-e KEY=value`, or hand over a whole file with `--env-file .env`.
**Secrets are never baked into the image** (`.env` is excluded from the build) —
always pass them at runtime.

| Variable | What it does | Default |
|----------|--------------|---------|
| `OPENROUTER_API_KEY` | Enables the LLM (planning, claim extraction, answer synthesis). Omit → deterministic fallback. | — |
| `OPENROUTER_MODEL` | Which model to use. | `openai/gpt-4o-mini` |
| `OPENROUTER_BASE_URL` | OpenAI-compatible endpoint. | OpenRouter |
| `RE_API_PORT` | Port the server listens on inside the container. | `8000` |
| `RE_MAX_WORKERS` | Thread-pool size for parallel search/extraction/reasoning. | `6` |
| `RE_MAX_ITERATIONS` | Research-loop budget (iterations). | `3` |
| `RE_MAX_SUBTOPICS` | Research angles per run (1–7). | `6` |
| `RE_DOCUMENTS_PER_QUERY` | Documents gathered per angle. | `3` |
| `RE_CONFIDENCE_THRESHOLD` | Stop once confidence ≥ this (0–1). | `0.7` |
| `RE_SEARCH_PROVIDER` | `web` (real sources) or `offline` (deterministic). | `web` |
| `RE_LLM_ENABLED` | `false` forces the no-LLM deterministic path. | `true` |
| `RE_HTTP_MAX_CONCURRENCY_PER_HOST` | Per-host request cap (raise `RE_MAX_WORKERS` safely). | `4` |
| `RE_LOG_LEVEL` | `DEBUG` / `INFO` / `WARNING` / `ERROR`. | `INFO` |
| `RE_OUTPUT_DIR` / `RE_SESSIONS_DIR` | Where reports / session JSON are written. | `/app/report`, `/app/sessions` |

### Volumes (keep reports after the container exits)

Reports and session snapshots are written inside the container and vanish with
it unless you mount host directories:

```bash
-v "$(pwd)/report:/app/report" \
-v "$(pwd)/sessions:/app/sessions"
```

> The container runs as an unprivileged user (uid 10001). If a mounted host
> directory isn't writable by that user, either `chmod 777` it first or add
> `--user "$(id -u):$(id -g)"` to the `docker run` command.

## Common recipes

**Real research, live logs, saved reports:**
```bash
docker run --rm -p 8000:8000 \
  -e OPENROUTER_API_KEY=sk-or-... \
  -v "$(pwd)/report:/app/report" \
  research-engine
```

**Use your existing `.env`:**
```bash
docker run --rm -p 8000:8000 --env-file .env research-engine
```

**Detached (background), then follow the same output:**
```bash
docker run -d --name re -p 8000:8000 research-engine
docker logs -f re
docker stop re            # --rm not used here, so also: docker rm re
```

**Turn up parallelism and depth:**
```bash
docker run --rm -p 8000:8000 \
  -e RE_MAX_WORKERS=10 -e RE_MAX_ITERATIONS=5 \
  -e OPENROUTER_API_KEY=sk-or-... \
  research-engine
```

**CLI instead of the server** (prints a report to the terminal; override the
default command):
```bash
docker run --rm -v "$(pwd)/report:/app/report" \
  research-engine research-engine "Quantum Computing" --offline --no-llm
```

## Health & lifecycle

- `GET /health` returns `{"status":"ok","version":"…"}`; the image also has a
  built-in `HEALTHCHECK` (`docker ps` shows `healthy`).
- Stop a foreground run with `Ctrl+C`; stop a detached one with `docker stop`.
- `--rm` auto-removes the container on exit (drop it if you want to inspect it
  afterward with `docker logs`).

## Notes

- The `uv:latest` line in the `Dockerfile` pulls the current uv at build time.
  Pin it (e.g. `ghcr.io/astral-sh/uv:0.9`) if you want fully reproducible builds.
- Rebuild after changing engine or frontend source: `docker build -t research-engine .`
  (Docker caches the dependency layers, so incremental rebuilds are fast.)
