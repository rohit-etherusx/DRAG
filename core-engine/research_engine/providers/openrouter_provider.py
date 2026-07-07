"""OpenRouter language-model provider (the default ``LLMProvider``).

OpenRouter exposes an OpenAI-compatible API, so this provider uses the ``openai``
client pointed at the OpenRouter base URL. It is used only for optional narrative
synthesis (e.g. the executive summary); the core pipeline never depends on it and
falls back to deterministic synthesis when the provider is unavailable.

The provider is *available* only when the ``openai`` SDK is importable and an
``OPENROUTER_API_KEY`` is present. The SDK is imported lazily so importing this
module has no side effects and the engine still runs when the key is absent.
"""
from __future__ import annotations

import os

from research_engine.config import DEFAULT_LLM_BASE_URL, DEFAULT_LLM_MODEL
from research_engine.logging_setup import get_logger
from research_engine.providers.base import LLMProvider

_log = get_logger("providers.openrouter")

#: Environment variable holding the OpenRouter API key.
API_KEY_ENV = "OPENROUTER_API_KEY"


def _sdk_importable() -> bool:
    try:
        import openai  # noqa: F401
    except Exception:  # pragma: no cover - depends on environment
        return False
    return True


class OpenRouterProvider(LLMProvider):
    """LLM provider backed by OpenRouter's OpenAI-compatible Chat API."""

    name = "openrouter"

    def __init__(
        self,
        model: str = DEFAULT_LLM_MODEL,
        base_url: str = DEFAULT_LLM_BASE_URL,
        max_tokens: int = 1500,
        timeout_seconds: float = 45.0,
        max_retries: int = 2,
    ) -> None:
        self.model = model
        self.base_url = base_url
        self.max_tokens = max_tokens
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._client = None

    @property
    def available(self) -> bool:
        return _sdk_importable() and bool(os.environ.get(API_KEY_ENV))

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(
                base_url=self.base_url,
                api_key=os.environ.get(API_KEY_ENV),
                # Bound each request so a stalled provider fails fast to the
                # deterministic fallback instead of hanging on the SDK's 600 s
                # default; retries are bounded so a hard failure can't multiply
                # that wait. Critical once acquisition runs concurrently — an
                # unbounded request would pin a worker thread for minutes.
                timeout=self.timeout_seconds,
                max_retries=self.max_retries,
            )
        return self._client

    def generate(
        self, prompt: str, system: str | None = None, *, json_object: bool = False
    ) -> str | None:
        if not self.available:
            return None
        try:
            client = self._get_client()
            # Structured-output mode makes JSON-returning calls (extraction, the
            # equivalence judge, the planner) far more reliable on models that
            # otherwise wrap JSON in prose. Providers/models that do not support
            # it either ignore the field or error — in which case the outer
            # except returns None and the caller falls back deterministically.
            extra = (
                {"response_format": {"type": "json_object"}} if json_object else {}
            )
            response = client.chat.completions.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[
                    {
                        "role": "system",
                        "content": system
                        or "You are a precise research synthesis assistant.",
                    },
                    {"role": "user", "content": prompt},
                ],
                **extra,
            )
            text = (response.choices[0].message.content or "").strip()
            return text or None
        except Exception as exc:  # pragma: no cover - network/credentials dependent
            _log.warning(
                "OpenRouter synthesis failed, falling back to deterministic: %s", exc
            )
            return None
