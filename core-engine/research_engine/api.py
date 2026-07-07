"""FastAPI HTTP interface for the Research Engine.

Exposes the engine over HTTP so a client can run a research session and receive
results as JSON — either in one blocking call (``POST /research``) or as a live
stream of progress events (``POST /research/stream``, Server-Sent Events). This
is a thin adapter: it builds an :class:`EngineConfig` from the request, delegates
to :func:`research_engine.service.run_research`, and serializes the result — no
research logic lives here (ARCHITECTURE.md, Layer 1).

The streaming endpoint reuses the engine's progress observer seam
(:mod:`research_engine.progress`): a background thread runs the blocking engine
while its ``progress`` reporter forwards each typed event onto the event loop,
which yields them as SSE frames. The web UI (``ui/``) consumes this to show a run
unfold in real time instead of waiting on a dead spinner.

When a built front-end is present (``ui/dist/`` or ``$RE_WEBAPP_DIR``) it is
served at ``/`` so ``research-engine-api`` is a single-command app.

FastAPI/uvicorn are optional dependencies (the ``api`` extra). Install with::

    uv sync --extra api          # or: pip install "research-engine[api]"

Run the server::

    uv run research-engine-api                       # console script
    uv run uvicorn research_engine.api:app --reload  # or via uvicorn directly
"""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict, is_dataclass
from pathlib import Path

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import StreamingResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel, Field
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    raise ImportError(
        "The HTTP API requires FastAPI. Install the optional 'api' extra:\n"
        "    uv sync --extra api    (or: pip install 'research-engine[api]')"
    ) from exc

from research_engine import __version__
from research_engine.config import EngineConfig
from research_engine.logging_setup import configure_logging, get_logger
from research_engine.progress import ProgressEvent
from research_engine.service import run_research
from research_engine.storage.storage import serialize_session

_log = get_logger("api")

#: Sentinel placed on the stream queue to signal the run has fully finished.
_STREAM_DONE = object()


class ResearchQuery(BaseModel):
    """Request body for a research run."""

    topic: str = Field(..., min_length=1, description="The topic to research.")
    max_subtopics: int | None = Field(
        default=None, ge=1, le=7, description="Number of research angles (1-7)."
    )
    documents_per_query: int | None = Field(
        default=None, ge=1, le=10, description="Documents gathered per angle."
    )
    max_iterations: int | None = Field(
        default=None, ge=1, le=10, description="Max research-loop iterations."
    )
    offline: bool = Field(
        default=False, description="Use the deterministic offline search provider."
    )
    no_llm: bool = Field(
        default=False, description="Disable the LLM; deterministic synthesis only."
    )


def _config_from_query(query: ResearchQuery) -> EngineConfig:
    """Build an :class:`EngineConfig` from a request, honouring ``.env`` defaults."""
    return EngineConfig.from_env(
        max_subtopics=query.max_subtopics,
        documents_per_query=query.documents_per_query,
        max_iterations=query.max_iterations,
        llm_enabled=(False if query.no_llm else None),
        search_provider=("offline" if query.offline else None),
    )


def _event_payload(event: ProgressEvent) -> dict:
    """Serialize a progress event to a JSON-safe dict tagged with its type.

    The ``type`` field is the event class name (e.g. ``"IterationDone"``); the UI
    switches on it. Dataclass fields are flattened alongside it.
    """
    fields = asdict(event) if is_dataclass(event) else {}
    return {"type": type(event).__name__, **fields}


def _sse(payload: dict) -> str:
    """Format a payload as a single Server-Sent Events frame."""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _resolve_webapp_dir() -> Path | None:
    """Return the built front-end directory to serve, if one exists.

    Order: ``$RE_WEBAPP_DIR`` if set, else ``<repo>/ui/dist`` inferred from this
    file's location. Returns ``None`` (API-only mode) when no build is present.
    """
    env_dir = os.environ.get("RE_WEBAPP_DIR")
    candidates = [Path(env_dir)] if env_dir else []
    # api.py -> research_engine -> core-engine -> <repo>; the UI build lives at
    # <repo>/ui/dist. This is best-effort: a wheel install without the repo
    # simply runs API-only.
    candidates.append(Path(__file__).resolve().parents[2] / "ui" / "dist")
    for path in candidates:
        if (path / "index.html").is_file():
            return path
    return None


def create_app() -> "FastAPI":
    """Build and return the FastAPI application."""
    configure_logging(os.environ.get("RE_LOG_LEVEL", "INFO"))
    app = FastAPI(
        title="Research Engine API",
        version=__version__,
        description="Autonomous, domain-agnostic research engine over HTTP.",
    )

    # The engine is a local research tool with no auth/cookies; permissive CORS
    # keeps the Vite dev server (and any local client) working out of the box.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict:
        """Liveness/version check."""
        return {"status": "ok", "version": __version__}

    @app.post("/research")
    def research(query: ResearchQuery) -> dict:
        """Run a full research session and return the session as JSON.

        Blocking: returns only when the run completes. Defined synchronously so
        FastAPI runs it in a worker thread and the engine call (network + LLM)
        does not stall the event loop. Prefer ``/research/stream`` for live UI.
        """
        config = _config_from_query(query)
        _log.info("API research request: %r", query.topic)
        try:
            session = run_research(query.topic, config)
        except ValueError as exc:  # e.g. empty topic
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # pragma: no cover - defensive
            _log.exception("Research run failed")
            raise HTTPException(
                status_code=500, detail=f"research failed: {exc}"
            ) from exc
        return serialize_session(session)

    @app.post("/research/stream")
    async def research_stream(query: ResearchQuery) -> StreamingResponse:
        """Run a session and stream progress as Server-Sent Events.

        Emits one SSE frame per progress event (``PlanReady``, ``IterationDone``,
        ``AnswerReady``, …), then a terminal ``SessionComplete`` frame carrying
        the full serialized session (or an ``Error`` frame). The engine runs on a
        worker thread; its progress reporter forwards events onto the event loop.
        """
        config = _config_from_query(query)
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def reporter(event: ProgressEvent) -> None:
            # Called from the orchestrator thread — hop back onto the loop.
            loop.call_soon_threadsafe(queue.put_nowait, _event_payload(event))

        def worker() -> None:
            try:
                session = run_research(query.topic, config, progress=reporter)
                final = {
                    "type": "SessionComplete",
                    "session": serialize_session(session),
                }
            except ValueError as exc:
                final = {"type": "Error", "status": 400, "detail": str(exc)}
            except Exception as exc:  # defensive: surface, never crash the stream
                _log.exception("Streaming research run failed")
                final = {
                    "type": "Error",
                    "status": 500,
                    "detail": f"research failed: {exc}",
                }
            loop.call_soon_threadsafe(queue.put_nowait, final)
            loop.call_soon_threadsafe(queue.put_nowait, _STREAM_DONE)

        async def event_stream():
            _log.info("API streaming research request: %r", query.topic)
            task = loop.run_in_executor(None, worker)
            try:
                while True:
                    payload = await queue.get()
                    if payload is _STREAM_DONE:
                        break
                    yield _sse(payload)
            finally:
                await task  # join the worker; re-raise any executor error
            yield _sse({"type": "Done"})

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                # Disable proxy buffering so frames flush immediately.
                "X-Accel-Buffering": "no",
            },
        )

    # Serve the built front-end at "/" when present. Mounted last so the API
    # routes above take precedence; html=True serves index.html for SPA routes.
    webapp_dir = _resolve_webapp_dir()
    if webapp_dir is not None:
        app.mount(
            "/", StaticFiles(directory=str(webapp_dir), html=True), name="webapp"
        )
        _log.info("Serving web UI from %s", webapp_dir)
    else:
        _log.info("No built web UI found; running API-only (build with: cd ui && npm run build)")

    return app


#: Module-level app so ``uvicorn research_engine.api:app`` works.
app = create_app()


def serve() -> None:
    """Console-script entry point: run the API with uvicorn.

    Host/port are read from ``RE_API_HOST`` / ``RE_API_PORT`` (defaults
    127.0.0.1:8000).
    """
    import uvicorn

    host = os.environ.get("RE_API_HOST", "127.0.0.1")
    port = int(os.environ.get("RE_API_PORT", "8000"))
    uvicorn.run("research_engine.api:app", host=host, port=port)


if __name__ == "__main__":
    serve()
