# syntax=docker/dockerfile:1
#
# Research Engine — single-image container.
#
# Builds the React/Vite web app, then serves it together with the FastAPI
# backend and the full engine from one Python image on one port (8000).
#
#   docker build -t research-engine .
#   docker run --rm -p 8000:8000 research-engine        # → http://localhost:8000
#
# See DOCKER.md for the full list of arguments and environment variables.

# ---------------------------------------------------------------------------
# Stage 1 — build the web frontend (produces /ui/dist)
# ---------------------------------------------------------------------------
FROM node:22-bookworm-slim AS ui-builder
WORKDIR /ui

# Install deps first from the lockfile so this layer caches across code changes.
COPY ui/package.json ui/package-lock.json ./
RUN npm ci

# Build the SPA. `npm run build` runs `tsc -b && vite build` → /ui/dist.
COPY ui/ ./
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2 — Python runtime (engine + API), serves the built UI at /
# ---------------------------------------------------------------------------
FROM python:3.13-slim-bookworm AS runtime

# uv: fast, reproducible installs straight from uv.lock.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

# Dependency layer: copy only what's needed to resolve + build the package, so
# `uv sync` is cached until the manifest, lockfile, or engine source changes.
# Install BOTH extras: `api` (the default web GUI + HTTP API) and `tui` (the
# animated terminal dashboard), so the one image can run either interface.
COPY pyproject.toml uv.lock README.md ./
COPY core-engine/ ./core-engine/
RUN uv sync --frozen --no-dev --extra api --extra tui

# Copy the built web app; the API serves it at / when RE_WEBAPP_DIR points here.
COPY --from=ui-builder /ui/dist ./ui/dist

# Runtime defaults: bind all interfaces (reachable from the host), serve the UI,
# and give the engine writable output dirs.
ENV PATH="/app/.venv/bin:$PATH" \
    RE_API_HOST=0.0.0.0 \
    RE_API_PORT=8000 \
    RE_WEBAPP_DIR=/app/ui/dist \
    RE_OUTPUT_DIR=/app/report \
    RE_SESSIONS_DIR=/app/sessions

# Run as an unprivileged user; give it ownership of the writable paths.
RUN mkdir -p /app/report /app/sessions \
 && useradd --create-home --uid 10001 appuser \
 && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Liveness probe (no curl in slim images, so use the stdlib).
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"]

# Default: run the API server (which also serves the web app). Override the
# command to run a different interface, e.g.
#   plain CLI:  docker run --rm research-engine research-engine "Quantum Computing"
#   live TUI:   docker run --rm -it research-engine research-engine-tui "Quantum Computing"
# (the TUI needs an interactive terminal — the -it flags — or it falls back to
# the plain CLI.)
CMD ["research-engine-api"]
