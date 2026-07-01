"""Engine configuration — the single source of runtime settings.

Configuration is a plain dataclass so it stays trivially testable and free of
framework magic. Values may be supplied programmatically, via a local ``.env``
file, via environment variables (``RE_*`` for engine settings, provider-specific
names such as ``OPENROUTER_*`` for the LLM), or overridden per-run by the CLI.

Precedence (lowest to highest): dataclass defaults → ``.env`` / environment →
explicit overrides (e.g. CLI flags).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

try:  # pragma: no cover - trivial import guard
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - dotenv is a declared dependency
    load_dotenv = None  # type: ignore[assignment]

#: Default OpenRouter model. Any model id from https://openrouter.ai/models is
#: valid; this is a small, widely-available, inexpensive default.
DEFAULT_LLM_MODEL = "openai/gpt-4o-mini"
#: OpenAI-compatible OpenRouter endpoint.
DEFAULT_LLM_BASE_URL = "https://openrouter.ai/api/v1"

_env_loaded = False


def load_environment() -> None:
    """Load a local ``.env`` file into ``os.environ`` exactly once.

    Existing environment variables are not overridden (``.env`` fills in only
    what is unset), and a missing file is a no-op. Safe to call repeatedly.
    """
    global _env_loaded
    if _env_loaded:
        return
    if load_dotenv is not None:
        load_dotenv(override=False)
    _env_loaded = True


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_first(names: tuple[str, ...], default: str) -> str:
    """Return the first non-empty environment value among ``names``."""
    for name in names:
        value = os.environ.get(name)
        if value is not None and value.strip() != "":
            return value
    return default


@dataclass
class EngineConfig:
    """Runtime configuration for a research session."""

    #: Directory where ``<topic>_report.md`` files are written.
    output_dir: str = "report"
    #: Directory where machine-readable session snapshots are written.
    sessions_dir: str = "sessions"
    #: Maximum number of sub-topic research questions the planner generates.
    max_subtopics: int = 6
    #: Number of documents the search provider returns per query.
    documents_per_query: int = 3
    #: Which search provider to use: "web" (real no-key sources) or "offline"
    #: (deterministic local-knowledge stub, used for reproducible/offline runs).
    search_provider: str = "web"
    #: Whether to use a live LLM provider when one is available.
    llm_enabled: bool = True
    #: Identifier of the active LLM provider (extension seam; OpenRouter default).
    llm_provider: str = "openrouter"
    #: Model id passed to the LLM provider.
    llm_model: str = DEFAULT_LLM_MODEL
    #: OpenAI-compatible base URL for the LLM provider.
    llm_base_url: str = DEFAULT_LLM_BASE_URL
    #: Output-token ceiling for LLM synthesis calls.
    llm_max_tokens: int = 1500
    #: Logging verbosity.
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, **overrides: object) -> "EngineConfig":
        """Build a config from defaults, then ``.env``/environment, then overrides.

        ``overrides`` values that are ``None`` are ignored so the CLI can pass
        optional flags through uniformly.
        """
        load_environment()
        cfg = cls(
            output_dir=os.environ.get("RE_OUTPUT_DIR", cls.output_dir),
            sessions_dir=os.environ.get("RE_SESSIONS_DIR", cls.sessions_dir),
            max_subtopics=_env_int("RE_MAX_SUBTOPICS", cls.max_subtopics),
            documents_per_query=_env_int(
                "RE_DOCUMENTS_PER_QUERY", cls.documents_per_query
            ),
            search_provider=os.environ.get("RE_SEARCH_PROVIDER", cls.search_provider),
            llm_enabled=_env_bool("RE_LLM_ENABLED", cls.llm_enabled),
            llm_provider=os.environ.get("RE_LLM_PROVIDER", cls.llm_provider),
            llm_model=_env_first(("RE_LLM_MODEL", "OPENROUTER_MODEL"), cls.llm_model),
            llm_base_url=_env_first(
                ("RE_LLM_BASE_URL", "OPENROUTER_BASE_URL"), cls.llm_base_url
            ),
            llm_max_tokens=_env_int("RE_LLM_MAX_TOKENS", cls.llm_max_tokens),
            log_level=os.environ.get("RE_LOG_LEVEL", cls.log_level),
        )
        for key, value in overrides.items():
            if value is not None:
                setattr(cfg, key, value)
        return cfg
