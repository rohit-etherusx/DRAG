"""Deterministic confidence estimation.

Confidence must be reproducible: identical inputs must always yield the identical
score (``OBJECTIVE.md`` problem 7). This module computes a 0..1 confidence from
measurable, evidence-derived inputs via a fixed, documented weighting — no
randomness, no model calls.

Inputs (each contributes a 0..1 factor):

* **supporting sources** — how many distinct sources assert the finding;
* **independent domains** — how many distinct network domains (independent
  corroboration is stronger than repeated assertion within one domain);
* **source authority** — mean authority of the contributing sources;
* **claim agreement** — corroboration strength from claim clustering;
* **extraction/relevance quality** — mean relevance of the supporting evidence.

A contradiction penalty reduces the score, and the result is capped below 1.0 so
a finding is never reported as certain (there is always room for one more
corroborating source).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

# Weights sum to 1.0. Sources and domains dominate (breadth of corroboration),
# with authority, agreement, and relevance as quality modifiers.
_W_SOURCES = 0.30
_W_DOMAINS = 0.20
_W_AUTHORITY = 0.20
_W_AGREEMENT = 0.15
_W_RELEVANCE = 0.15

#: Saturation points: this many sources/domains reach the full factor.
_SOURCE_TARGET = 3.0
_DOMAIN_TARGET = 3.0
#: Per-contradiction penalty and its cap.
_CONTRADICTION_PENALTY = 0.1
_MAX_CONTRADICTION_PENALTY = 0.4
#: Confidence ceiling — never fully certain.
_CEILING = 0.95


@dataclass(frozen=True)
class ConfidenceInputs:
    """Measurable inputs to a confidence estimate."""

    supporting_sources: int = 0
    independent_domains: int = 0
    mean_authority: float = 0.0
    agreement: float = 0.0
    contradictions: int = 0
    mean_relevance: float = 0.0


class ConfidenceModel:
    """Turns :class:`ConfidenceInputs` into a deterministic 0..1 score."""

    def score(self, inputs: ConfidenceInputs) -> float:
        source_factor = min(1.0, inputs.supporting_sources / _SOURCE_TARGET)
        domain_factor = min(1.0, inputs.independent_domains / _DOMAIN_TARGET)
        authority_factor = _clamp01(inputs.mean_authority)
        agreement_factor = _clamp01(inputs.agreement)
        relevance_factor = _clamp01(inputs.mean_relevance)

        base = (
            _W_SOURCES * source_factor
            + _W_DOMAINS * domain_factor
            + _W_AUTHORITY * authority_factor
            + _W_AGREEMENT * agreement_factor
            + _W_RELEVANCE * relevance_factor
        )
        penalty = min(
            _MAX_CONTRADICTION_PENALTY,
            _CONTRADICTION_PENALTY * max(0, inputs.contradictions),
        )
        return round(min(_CEILING, max(0.0, base - penalty)), 4)

    def breakdown(self, inputs: ConfidenceInputs) -> dict[str, float]:
        """Return the inputs plus the resulting score, for explainability/logs."""
        data = {k: float(v) for k, v in asdict(inputs).items()}
        data["confidence"] = self.score(inputs)
        return data


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))
