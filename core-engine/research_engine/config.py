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


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
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

    # --- v0.4: candidate evaluation / claim pipeline / research loop ------
    #: Master switch for the candidate-evaluation gate. When off, every search
    #: candidate is downloaded (no metadata filtering) — useful for A/B runs.
    evaluation_enabled: bool = True
    #: Search candidates retrieved per generated search query (metadata only).
    max_candidates_per_query: int = 8
    #: Minimum 0..1 relevance (scored on title/snippet/URL only) a candidate
    #: must reach to be downloaded. Below this it is rejected before download.
    candidate_relevance_threshold: float = 0.15
    #: Optional 0..1 authority gate. 0.0 disables authority-based rejection
    #: (authority still feeds confidence). Raise to also drop low-authority sources.
    min_authority: float = 0.0
    #: Maximum number of passages kept per document for claim extraction.
    max_passages: int = 6
    #: Minimum 0..1 passage relevance to keep a passage (fail-open if none pass).
    passage_min_relevance: float = 0.05
    #: Master switch for claim verification (clustering, agreement, contradictions).
    verification_enabled: bool = True
    #: Research loop: stop iterating once overall confidence reaches this value.
    confidence_threshold: float = 0.7
    #: Research loop: search budget — maximum retrieval→verification iterations.
    max_iterations: int = 3

    # --- v0.5: research intelligence / agent loop --------------------------
    #: Claims below this 0..1 importance are excluded from reasoning and the
    #: report (they stay in the session for audit). 0.0 keeps everything.
    min_claim_importance: float = 0.1
    #: Stop iterating when an iteration's 0..1 knowledge gain falls below this
    #: (searching has stopped teaching the engine anything new).
    min_iteration_gain: float = 0.05
    #: Stop when overall confidence changed less than this across the last two
    #: iterations (confidence has stabilized short of the threshold).
    min_confidence_delta: float = 0.02
    #: Maximum search tasks the adaptive planner may emit per iteration.
    max_search_tasks_per_iteration: int = 6
    #: Maximum borderline claim pairs the semantic equivalence judge reviews
    #: per verification pass (0 disables the judge even when an LLM is on).
    max_equivalence_checks: int = 40

    # --- v0.6: performance / concurrency -----------------------------------
    #: Maximum concurrent worker threads for I/O-bound acquisition (per-
    #: subquestion search + download, then per-document claim extraction).
    #: The work is I/O-bound so threads parallelize despite the GIL. Set to 1
    #: to force fully sequential execution. Determinism is preserved regardless:
    #: results are merged into the research state single-threaded, in task order.
    max_workers: int = 6
    #: Per-request timeout (seconds) for LLM calls. Bounds a stalled provider
    #: request so it fails fast to the deterministic fallback instead of hanging
    #: on the SDK's 600 s default (the root cause of observed 10-minute stalls).
    llm_timeout_seconds: float = 45.0
    #: Automatic retries the LLM client makes on a failed/timed-out request.
    llm_max_retries: int = 2

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
            evaluation_enabled=_env_bool(
                "RE_EVALUATION_ENABLED", cls.evaluation_enabled
            ),
            max_candidates_per_query=_env_int(
                "RE_MAX_CANDIDATES_PER_QUERY", cls.max_candidates_per_query
            ),
            candidate_relevance_threshold=_env_float(
                "RE_CANDIDATE_RELEVANCE_THRESHOLD", cls.candidate_relevance_threshold
            ),
            min_authority=_env_float("RE_MIN_AUTHORITY", cls.min_authority),
            max_passages=_env_int("RE_MAX_PASSAGES", cls.max_passages),
            passage_min_relevance=_env_float(
                "RE_PASSAGE_MIN_RELEVANCE", cls.passage_min_relevance
            ),
            verification_enabled=_env_bool(
                "RE_VERIFICATION_ENABLED", cls.verification_enabled
            ),
            confidence_threshold=_env_float(
                "RE_CONFIDENCE_THRESHOLD", cls.confidence_threshold
            ),
            max_iterations=_env_int("RE_MAX_ITERATIONS", cls.max_iterations),
            min_claim_importance=_env_float(
                "RE_MIN_CLAIM_IMPORTANCE", cls.min_claim_importance
            ),
            min_iteration_gain=_env_float(
                "RE_MIN_ITERATION_GAIN", cls.min_iteration_gain
            ),
            min_confidence_delta=_env_float(
                "RE_MIN_CONFIDENCE_DELTA", cls.min_confidence_delta
            ),
            max_search_tasks_per_iteration=_env_int(
                "RE_MAX_SEARCH_TASKS_PER_ITERATION",
                cls.max_search_tasks_per_iteration,
            ),
            max_equivalence_checks=_env_int(
                "RE_MAX_EQUIVALENCE_CHECKS", cls.max_equivalence_checks
            ),
            max_workers=_env_int("RE_MAX_WORKERS", cls.max_workers),
            llm_timeout_seconds=_env_float(
                "RE_LLM_TIMEOUT_SECONDS", cls.llm_timeout_seconds
            ),
            llm_max_retries=_env_int("RE_LLM_MAX_RETRIES", cls.llm_max_retries),
            log_level=os.environ.get("RE_LOG_LEVEL", cls.log_level),
        )
        for key, value in overrides.items():
            if value is not None:
                setattr(cfg, key, value)
        return cfg
