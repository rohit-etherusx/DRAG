"""Semantic claim-equivalence judgment.

Deterministic clustering can only merge near-identical wordings: on real
extracted claims, genuine cross-source paraphrases ("Self-attention captures
long-range context" / "The self-attention mechanism helps capture the context
of words") score *below* unrelated claims that share topic vocabulary, so no
lexical threshold can separate them. Judging whether two specific sentences
assert the same fact is a genuinely semantic task — one of the few places an
LLM is justified (``IMPLEMENTATION.md`` LLM rules: a reasoning tool over
provided claims, never a knowledge source).

The judge receives *pairs of claims already found borderline-similar* by the
deterministic clusterer (with polarity and numeric-conflict guards applied)
and answers, for each pair, whether both sentences assert the same fact. One
strict-JSON call covers all pairs. Every failure path — no LLM, unusable
output, an out-of-range index — degrades to "not equivalent", so the judge can
only ever *add* corroboration the clusterer missed, never fabricate structure
on its own, and offline runs remain fully deterministic.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from research_engine.domain.models import Claim
from research_engine.logging_setup import get_logger
from research_engine.providers.base import LLMProvider
from research_engine.utils import parse_json_object

_log = get_logger("verification.equivalence")


class ClaimEquivalenceJudge(ABC):
    """Decides whether borderline-similar claim pairs assert the same fact."""

    @abstractmethod
    def equivalent(self, pairs: list[tuple[Claim, Claim]]) -> list[bool]:
        """One verdict per pair; ``True`` means the claims are equivalent."""
        raise NotImplementedError


class LLMEquivalenceJudge(ClaimEquivalenceJudge):
    """Judges claim equivalence with one strict-JSON LLM call per batch."""

    def __init__(self, llm: LLMProvider, attempts: int = 2) -> None:
        self._llm = llm
        self._attempts = max(1, attempts)

    def equivalent(self, pairs: list[tuple[Claim, Claim]]) -> list[bool]:
        if not pairs or not self._llm.available:
            return [False] * len(pairs)

        pair_lines = "\n".join(
            f"[{index}]\nA: {a.text}\nB: {b.text}"
            for index, (a, b) in enumerate(pairs)
        )
        prompt = (
            "For each numbered pair of claims below, decide whether A and B "
            "assert the SAME fact — the same statement about the same subject, "
            "possibly worded differently. Claims that are merely related, "
            "about the same topic, or where one asserts something the other "
            "does not, are NOT equivalent. When unsure, answer not equivalent."
            "\n\nReturn ONLY a JSON object with key \"equivalent\": an array "
            "of the integer pair numbers that are equivalent (empty array if "
            "none). No prose.\n\n"
            f"PAIRS:\n{pair_lines}"
        )
        for _attempt in range(self._attempts):
            raw = self._llm.generate(
                prompt,
                system=(
                    "You judge whether claim pairs assert the same fact. "
                    "You answer as strict JSON and never merge claims that "
                    "merely share a topic."
                ),
                json_object=True,
            )
            verdicts = _parse_verdicts(raw, len(pairs))
            if verdicts is not None:
                return verdicts
        _log.warning(
            "Equivalence judgment unusable after %d attempt(s); "
            "treating %d borderline pair(s) as not equivalent",
            self._attempts,
            len(pairs),
        )
        return [False] * len(pairs)


def _parse_verdicts(raw: str | None, count: int) -> list[bool] | None:
    """Parse the judge response into per-pair verdicts (``None`` if unusable)."""
    data = parse_json_object(raw)
    if data is None or not isinstance(data.get("equivalent"), list):
        return None
    verdicts = [False] * count
    for item in data["equivalent"]:
        try:
            index = int(item)
        except (TypeError, ValueError):
            continue
        if 0 <= index < count:
            verdicts[index] = True
    return verdicts
