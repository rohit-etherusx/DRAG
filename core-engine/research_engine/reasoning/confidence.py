"""Deterministic confidence estimation.

Confidence must be reproducible: identical inputs must always yield the
identical score — no randomness, no model calls. And it must never depend
solely on source count (``OBJECTIVE.md`` confidence model): the score combines
independent sources, source authority, claim agreement, contradictions,
coverage of the research plan, evidence quality, and claim specificity, via a
fixed, documented weighting. Every score is returned with its factor breakdown
and a plain-language explanation.

Two granularities share the same formula:

* **finding / overall** scores include *coverage* (how much of the research
  plan is supported by verified evidence);
* **claim** scores have no meaningful coverage input, so the coverage weight is
  renormalized across the remaining factors (pass ``coverage=None``).
"""
from __future__ import annotations

from dataclasses import dataclass

from research_engine.domain.models import ClaimType, ConfidenceReport

# Weights sum to 1.0. Breadth of independent corroboration dominates, with
# authority, agreement, coverage, evidence quality, and specificity as
# quality modifiers.
_WEIGHTS = {
    "sources": 0.20,
    "domains": 0.15,
    "authority": 0.15,
    "agreement": 0.15,
    "coverage": 0.15,
    "evidence_quality": 0.10,
    "specificity": 0.10,
}

#: Saturation points: this many sources/domains reach the full factor.
_SOURCE_TARGET = 3.0
_DOMAIN_TARGET = 3.0
#: Per-contradiction penalty and its cap.
_CONTRADICTION_PENALTY = 0.1
_MAX_CONTRADICTION_PENALTY = 0.4
#: Confidence ceiling — never fully certain.
_CEILING = 0.95

#: How specific each claim type is (numbers and dates are checkable; open
#: questions assert nothing).
_TYPE_SPECIFICITY = {
    ClaimType.NUMERICAL: 1.0,
    ClaimType.DATE: 1.0,
    ClaimType.DEFINITION: 0.8,
    ClaimType.METHOD: 0.6,
    ClaimType.LIMITATION: 0.6,
    ClaimType.ASSUMPTION: 0.5,
    ClaimType.FACT: 0.4,
    ClaimType.OPEN_QUESTION: 0.1,
}


@dataclass(frozen=True)
class ConfidenceInputs:
    """Measurable inputs to a confidence estimate."""

    supporting_sources: int = 0
    independent_domains: int = 0
    mean_authority: float = 0.0
    agreement: float = 0.0
    contradictions: int = 0
    #: Fraction of the research plan supported by verified evidence;
    #: ``None`` for claim-level scores (weight is renormalized away).
    coverage: float | None = None
    evidence_quality: float = 0.0
    specificity: float = 0.0


class ConfidenceModel:
    """Turns :class:`ConfidenceInputs` into a deterministic, explained score."""

    def score(self, inputs: ConfidenceInputs) -> float:
        factors = {
            "sources": min(1.0, inputs.supporting_sources / _SOURCE_TARGET),
            "domains": min(1.0, inputs.independent_domains / _DOMAIN_TARGET),
            "authority": _clamp01(inputs.mean_authority),
            "agreement": _clamp01(inputs.agreement),
            "evidence_quality": _clamp01(inputs.evidence_quality),
            "specificity": _clamp01(inputs.specificity),
        }
        if inputs.coverage is not None:
            factors["coverage"] = _clamp01(inputs.coverage)

        total_weight = sum(_WEIGHTS[name] for name in factors)
        base = sum(_WEIGHTS[name] * value for name, value in factors.items())
        base /= total_weight  # renormalize when coverage is absent

        penalty = min(
            _MAX_CONTRADICTION_PENALTY,
            _CONTRADICTION_PENALTY * max(0, inputs.contradictions),
        )
        return round(min(_CEILING, max(0.0, base - penalty)), 4)

    def report(self, inputs: ConfidenceInputs) -> ConfidenceReport:
        """Score plus the factor breakdown and a plain-language explanation."""
        score = self.score(inputs)
        return ConfidenceReport(
            score=score,
            independent_sources=inputs.supporting_sources,
            authority=round(_clamp01(inputs.mean_authority), 4),
            agreement=round(_clamp01(inputs.agreement), 4),
            coverage=round(_clamp01(inputs.coverage or 0.0), 4),
            contradictions=inputs.contradictions,
            evidence_quality=round(_clamp01(inputs.evidence_quality), 4),
            specificity=round(_clamp01(inputs.specificity), 4),
            explanation=self.explain(inputs, score),
        )

    def explain(self, inputs: ConfidenceInputs, score: float) -> str:
        """One-sentence, deterministic explanation of a score."""
        parts = [
            f"{inputs.supporting_sources} independent source(s) across "
            f"{inputs.independent_domains} domain(s)",
            f"mean source authority {inputs.mean_authority:.0%}",
            f"cross-source agreement {inputs.agreement:.0%}",
        ]
        if inputs.coverage is not None:
            parts.append(f"plan coverage {inputs.coverage:.0%}")
        parts.append(f"evidence quality {inputs.evidence_quality:.0%}")
        parts.append(f"specificity {inputs.specificity:.0%}")
        if inputs.contradictions:
            parts.append(
                f"reduced by {inputs.contradictions} contradiction(s)"
            )
        return f"Confidence {score:.0%}: " + "; ".join(parts) + "."

def claim_specificity(claim_type: ClaimType) -> float:
    """0..1 specificity of a claim type (documented, deterministic)."""
    return _TYPE_SPECIFICITY.get(claim_type, 0.4)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))
