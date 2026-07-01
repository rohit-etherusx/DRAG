"""FastAPI HTTP interface for the Research Engine.

Exposes the engine over HTTP so a client can POST a topic and receive the full
research session as JSON. This is a thin adapter: it builds an
:class:`EngineConfig` from the request, delegates to
:func:`research_engine.service.run_research`, and serializes the resulting
session — no research logic lives here.

FastAPI/uvicorn are optional dependencies (the ``api`` extra). Install with::

    uv sync --extra api          # or: pip install "research-engine[api]"

Run the server::

    uv run research-engine-api                       # console script
    uv run uvicorn research_engine.api:app --reload  # or via uvicorn directly
"""
from __future__ import annotations

import os

try:
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel, Field
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    raise ImportError(
        "The HTTP API requires FastAPI. Install the optional 'api' extra:\n"
        "    uv sync --extra api    (or: pip install 'research-engine[api]')"
    ) from exc

from research_engine import __version__
from research_engine.config import EngineConfig
from research_engine.logging_setup import configure_logging, get_logger
from research_engine.service import run_research
from research_engine.storage.storage import serialize_session

_log = get_logger("api")


class ResearchQuery(BaseModel):
    """Request body for a research run."""

    topic: str = Field(..., min_length=1, description="The topic to research.")
    max_subtopics: int | None = Field(
        default=None, ge=1, le=7, description="Number of research angles (1-7)."
    )
    documents_per_query: int | None = Field(
        default=None, ge=1, description="Documents gathered per angle."
    )
    offline: bool = Field(
        default=False, description="Use the deterministic offline search provider."
    )
    no_llm: bool = Field(
        default=False, description="Disable the LLM; deterministic synthesis only."
    )


def create_app() -> "FastAPI":
    """Build and return the FastAPI application."""
    configure_logging(os.environ.get("RE_LOG_LEVEL", "INFO"))
    app = FastAPI(
        title="Research Engine API",
        version=__version__,
        description="Autonomous, domain-agnostic research engine over HTTP.",
    )

    @app.get("/health")
    def health() -> dict:
        """Liveness/version check."""
        return {"status": "ok", "version": __version__}

    @app.post("/research")
    def research(query: ResearchQuery) -> dict:
        """Run a full research session and return the session as JSON.

        Defined as a synchronous endpoint so FastAPI runs it in a worker thread —
        the engine call is blocking (network + LLM) and must not stall the event
        loop.
        """
        config = EngineConfig.from_env(
            max_subtopics=query.max_subtopics,
            documents_per_query=query.documents_per_query,
            llm_enabled=(False if query.no_llm else None),
            search_provider=("offline" if query.offline else None),
        )
        _log.info("API research request: %r", query.topic)
        try:
            session = run_research(query.topic, config)
        except ValueError as exc:  # e.g. empty topic
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # pragma: no cover - defensive
            _log.exception("Research run failed")
            raise HTTPException(status_code=500, detail=f"research failed: {exc}") from exc
        return serialize_session(session)

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
