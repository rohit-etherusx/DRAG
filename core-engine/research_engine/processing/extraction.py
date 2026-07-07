"""Claim extraction strategies.

Turning evidence passages into structured, *typed* claims is what replaces
document summarization (``OBJECTIVE.md`` module 5). For every passage the
extractor produces factual claims, definitions, numerical data, dates,
limitations, assumptions, methods, and open questions — as structured data,
never summaries. Two strategies implement the same :class:`ClaimExtractor`
interface:

* :class:`HeuristicClaimExtractor` — deterministic sentence splitting, a
  rule-based claim-type classifier, and capitalized-token entity spotting.
  Zero-cost, offline, always available.
* :class:`LLMClaimExtractor` — sends a document's extracted passages (never the
  raw document) to the LLM and asks for typed claims as strict JSON. It falls
  back to the heuristic extractor whenever the model is unavailable or returns
  unusable output.

Every extracted claim carries the id of the evidence passage it came from, so
the provenance chain (claim → evidence → document → source) is never broken.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from research_engine.domain.models import ClaimType, Evidence, RawDocument
from research_engine.logging_setup import get_logger
from research_engine.providers.base import LLMProvider
from research_engine.utils import (
    extract_entity_names,
    parse_json_object,
    split_sentences,
    string_list,
)

_log = get_logger("processing.extraction")


@dataclass
class ExtractedClaim:
    """A typed claim as extracted from one evidence passage, pre-normalization."""

    text: str
    claim_type: ClaimType = ClaimType.FACT
    entities: list[str] = field(default_factory=list)
    #: The evidence passage the claim was extracted from.
    evidence_id: str = ""


class ClaimExtractor(ABC):
    """Extracts typed claims from a document's evidence passages."""

    @abstractmethod
    def extract(
        self, document: RawDocument, evidence: list[Evidence]
    ) -> list[ExtractedClaim]:
        """Return the claims asserted by ``document``'s ``evidence`` passages."""
        raise NotImplementedError


# -- deterministic claim-type classification ---------------------------------

_YEAR_RE = re.compile(r"\b(1[5-9]\d{2}|20\d{2})\b")
_NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)?%?\b")
_DEFINITION_RE = re.compile(
    r"\b(is defined as|refers to|is a |is an |are a |are an |is the term|"
    r"is known as|means )", re.IGNORECASE,
)
_LIMITATION_RE = re.compile(
    r"\b(limitation|limited|cannot|can not|challenge|drawback|weakness|"
    r"not fully|remains? (unresolved|unclear|unknown|an open))", re.IGNORECASE,
)
_ASSUMPTION_RE = re.compile(r"\b(assumes?|assumption|assuming)\b", re.IGNORECASE)
_METHOD_RE = re.compile(
    r"\b(method|methodology|approach|technique|procedure|algorithm|protocol|"
    r"is measured|is assessed|is evaluated)\b", re.IGNORECASE,
)


def classify_claim(text: str) -> ClaimType:
    """Deterministically classify a claim sentence into a :class:`ClaimType`.

    Rule order encodes specificity: an explicit question outranks everything;
    definitions, assumptions, limitations, and methods outrank the presence of
    a number or date; a date outranks a generic number; anything else is a fact.
    """
    stripped = text.strip()
    if stripped.endswith("?"):
        return ClaimType.OPEN_QUESTION
    if _DEFINITION_RE.search(stripped):
        return ClaimType.DEFINITION
    if _ASSUMPTION_RE.search(stripped):
        return ClaimType.ASSUMPTION
    if _LIMITATION_RE.search(stripped):
        return ClaimType.LIMITATION
    if _METHOD_RE.search(stripped):
        return ClaimType.METHOD
    if _YEAR_RE.search(stripped):
        return ClaimType.DATE
    if _NUMBER_RE.search(stripped):
        return ClaimType.NUMERICAL
    return ClaimType.FACT


class HeuristicClaimExtractor(ClaimExtractor):
    """Deterministic, offline extraction: one typed claim per sentence."""

    def __init__(self, topic_keywords: list[str] | None = None) -> None:
        self._topic_keywords = topic_keywords or []

    def extract(
        self, document: RawDocument, evidence: list[Evidence]
    ) -> list[ExtractedClaim]:
        claims: list[ExtractedClaim] = []
        for item in evidence:
            for sentence in split_sentences(item.passage):
                claims.append(
                    ExtractedClaim(
                        text=sentence,
                        claim_type=classify_claim(sentence),
                        entities=extract_entity_names(sentence, self._topic_keywords),
                        evidence_id=item.id,
                    )
                )
        return claims


class LLMClaimExtractor(ClaimExtractor):
    """Extracts typed claims by prompting an LLM with the evidence passages."""

    def __init__(
        self,
        llm: LLMProvider,
        objective: str,
        fallback: ClaimExtractor,
        max_claims: int = 10,
        attempts: int = 2,
    ) -> None:
        self._llm = llm
        self._objective = objective
        self._fallback = fallback
        self._max_claims = max_claims
        self._attempts = max(1, attempts)

    def extract(
        self, document: RawDocument, evidence: list[Evidence]
    ) -> list[ExtractedClaim]:
        if not self._llm.available or not evidence:
            return self._fallback.extract(document, evidence)

        passage_lines = "\n".join(
            f"[{index}] {item.passage}" for index, item in enumerate(evidence)
        )
        type_names = ", ".join(t.value for t in ClaimType)
        prompt = (
            f"You are extracting evidence for research on: {self._objective}\n"
            f"From the numbered source PASSAGES below, extract up to "
            f"{self._max_claims} concise, self-contained claims relevant to the "
            f"research. Extract factual claims, definitions, numerical data, "
            f"dates, limitations, assumptions, methods, and open questions — "
            f"never summaries. Every claim must be supported by the passage it "
            f"cites; do not add outside knowledge or speculation.\n\n"
            f"Return ONLY a JSON object with key \"claims\": an array of objects "
            f"with:\n"
            f'  "claim": the claim as one self-contained sentence,\n'
            f'  "type": one of [{type_names}],\n'
            f'  "entities": array of the named entities/concepts it mentions,\n'
            f'  "passage": the integer index of the supporting passage.\n'
            f"No prose.\n\n"
            f"SOURCE TITLE: {document.title}\n"
            f"PASSAGES:\n{passage_lines}"
        )
        # The LLM is nondeterministic and can occasionally return unusable output
        # or a transient error; retry a few times before falling back.
        for _attempt in range(self._attempts):
            raw = self._llm.generate(
                prompt,
                system="You extract typed, source-grounded claims as strict JSON.",
                json_object=True,
            )
            claims = _parse_claims(raw, evidence, self._max_claims)
            if claims:
                return claims
        _log.warning(
            "LLM extraction unusable for %s after %d attempt(s); heuristic fallback",
            document.source.id,
            self._attempts,
        )
        return self._fallback.extract(document, evidence)


def _parse_claims(
    raw: str | None, evidence: list[Evidence], max_claims: int
) -> list[ExtractedClaim]:
    """Parse the LLM response into extracted claims (``[]`` when unusable)."""
    data = parse_json_object(raw)
    if data is None:
        return []
    valid_types = {t.value: t for t in ClaimType}
    claims: list[ExtractedClaim] = []
    for item in data.get("claims", []):
        if not isinstance(item, dict):
            continue
        text = str(item.get("claim", "")).strip()
        if not text:
            continue
        claim_type = valid_types.get(
            str(item.get("type", "")).strip().lower(), ClaimType.FACT
        )
        try:
            passage_index = int(item.get("passage", 0))
        except (TypeError, ValueError):
            passage_index = 0
        if not 0 <= passage_index < len(evidence):
            passage_index = 0
        claims.append(
            ExtractedClaim(
                text=text,
                claim_type=claim_type,
                entities=string_list(item.get("entities", []), 8),
                evidence_id=evidence[passage_index].id,
            )
        )
        if len(claims) >= max_claims:
            break
    return claims


def build_extractor(
    llm: LLMProvider | None,
    objective: str,
    topic_keywords: list[str] | None = None,
    *,
    enabled: bool = True,
) -> ClaimExtractor:
    """Select the claim extractor for a run.

    Uses the LLM extractor when an LLM is enabled and available, otherwise the
    deterministic heuristic extractor. The heuristic extractor is always the
    fallback, so extraction never fails outright.
    """
    heuristic = HeuristicClaimExtractor(topic_keywords)
    if enabled and llm is not None and llm.available:
        return LLMClaimExtractor(llm, objective, fallback=heuristic)
    return heuristic
