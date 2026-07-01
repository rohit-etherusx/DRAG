"""Claim and relationship extraction strategies.

Converting a raw document into structured knowledge — factual claims (each with
salient entities) and relationships between those entities — is the step that
turns fetched text into evidence and knowledge-graph edges. Two strategies
implement the same :class:`ClaimExtractor` interface:

* :class:`HeuristicClaimExtractor` — deterministic sentence-splitting plus
  capitalized-token entity spotting (no relationships). Zero-cost, offline,
  always available.
* :class:`LLMClaimExtractor` — reads the real source text and asks the LLM to
  extract self-contained claims, their entities, and relationships between
  entities. This is what grounds the pipeline in genuinely analyzed source
  content; it falls back to the heuristic extractor whenever the model is
  unavailable or returns unusable output.

Keeping extraction behind an interface means the processor, knowledge graph, and
reasoning subsystems are unaffected by which strategy is used.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from research_engine.domain.models import RawDocument
from research_engine.logging_setup import get_logger
from research_engine.providers.base import LLMProvider
from research_engine.utils import extract_entity_names, split_sentences

_log = get_logger("processing.extraction")


@dataclass
class ExtractedClaim:
    """A candidate claim plus the entities it mentions, prior to normalization."""

    text: str
    entities: list[str] = field(default_factory=list)


@dataclass
class ExtractedRelationship:
    """A directed relationship between two entities, as stated by a source."""

    source: str
    relation: str
    target: str


@dataclass
class ExtractionResult:
    """Everything extracted from a single document."""

    claims: list[ExtractedClaim] = field(default_factory=list)
    relationships: list[ExtractedRelationship] = field(default_factory=list)


class ClaimExtractor(ABC):
    """Extracts structured knowledge from a single document."""

    @abstractmethod
    def extract(self, document: RawDocument) -> ExtractionResult:
        raise NotImplementedError


class HeuristicClaimExtractor(ClaimExtractor):
    """Deterministic, offline extraction (the v0.1 behavior; no relationships)."""

    def __init__(self, topic_keywords: list[str] | None = None) -> None:
        self._topic_keywords = topic_keywords or []

    def extract(self, document: RawDocument) -> ExtractionResult:
        claims = [
            ExtractedClaim(
                text=sentence,
                entities=extract_entity_names(sentence, self._topic_keywords),
            )
            for sentence in split_sentences(document.content)
        ]
        return ExtractionResult(claims=claims, relationships=[])


class LLMClaimExtractor(ClaimExtractor):
    """Extracts claims, entities, and relationships by prompting an LLM."""

    def __init__(
        self,
        llm: LLMProvider,
        topic: str,
        fallback: ClaimExtractor,
        max_claims: int = 8,
        max_relationships: int = 8,
        max_input_chars: int = 4000,
        attempts: int = 2,
    ) -> None:
        self._llm = llm
        self._topic = topic
        self._fallback = fallback
        self._max_claims = max_claims
        self._max_relationships = max_relationships
        self._max_input_chars = max_input_chars
        self._attempts = max(1, attempts)

    def extract(self, document: RawDocument) -> ExtractionResult:
        if not self._llm.available:
            return self._fallback.extract(document)

        content = document.content[: self._max_input_chars]
        prompt = (
            f"You are extracting evidence for research on '{self._topic}'.\n"
            f"From the SOURCE below, extract:\n"
            f"1. up to {self._max_claims} concise, self-contained factual claims "
            f"relevant to the topic, each with the key named entities/concepts it "
            f"mentions;\n"
            f"2. up to {self._max_relationships} relationships between those "
            f"entities, each as source entity, a short relation phrase, and target "
            f"entity.\n"
            f"Everything must be supported by the source text — do not add outside "
            f"knowledge or speculation.\n\n"
            f"Return ONLY a JSON object with keys:\n"
            f'  "claims": array of objects with "claim" (string) and "entities" '
            f"(array of strings),\n"
            f'  "relationships": array of objects with "source" (string), '
            f'"relation" (string), "target" (string).\n'
            f"No prose.\n\n"
            f"SOURCE TITLE: {document.title}\n"
            f"SOURCE TEXT:\n{content}"
        )
        # The LLM is nondeterministic and can occasionally return unusable output
        # or a transient error; retry a few times before falling back.
        for attempt in range(self._attempts):
            raw = self._llm.generate(
                prompt,
                system="You extract structured, source-grounded knowledge as strict JSON.",
            )
            result = _parse_extraction(raw, self._max_claims, self._max_relationships)
            if result is not None:
                return result
        _log.warning(
            "LLM extraction unusable for %s after %d attempt(s); heuristic fallback",
            document.source.id,
            self._attempts,
        )
        return self._fallback.extract(document)


def _parse_extraction(
    raw: str | None, max_claims: int, max_relationships: int
) -> ExtractionResult | None:
    """Parse the LLM response into an :class:`ExtractionResult`, or ``None``."""
    if not raw:
        return None
    payload = _extract_json_object(raw)
    if payload is None:
        return None
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    claims = _parse_claims(data.get("claims", []), max_claims)
    relationships = _parse_relationships(data.get("relationships", []), max_relationships)
    if not claims:
        return None  # a result with no usable claims is not worth keeping
    return ExtractionResult(claims=claims, relationships=relationships)


def _parse_claims(data, max_claims: int) -> list[ExtractedClaim]:
    if not isinstance(data, list):
        return []
    claims: list[ExtractedClaim] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        text = str(item.get("claim", "")).strip()
        if not text:
            continue
        entities_raw = item.get("entities", [])
        if not isinstance(entities_raw, list):
            entities_raw = []
        entities = [str(e).strip() for e in entities_raw if str(e).strip()]
        claims.append(ExtractedClaim(text=text, entities=entities))
        if len(claims) >= max_claims:
            break
    return claims


def _parse_relationships(data, max_relationships: int) -> list[ExtractedRelationship]:
    if not isinstance(data, list):
        return []
    relationships: list[ExtractedRelationship] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source", "")).strip()
        target = str(item.get("target", "")).strip()
        relation = str(item.get("relation", "")).strip() or "related to"
        if not source or not target or source.lower() == target.lower():
            continue
        relationships.append(ExtractedRelationship(source, relation, target))
        if len(relationships) >= max_relationships:
            break
    return relationships


def _extract_json_object(raw: str) -> str | None:
    """Return a JSON object substring from ``raw`` (best-effort).

    Strips a Markdown code fence if present, then falls back to the span from the
    first ``{`` to the last ``}``.
    """
    text = raw.strip()
    if "```" in text:
        # Prefer the contents of the first fenced code block.
        fence = text.split("```", 2)
        if len(fence) >= 2:
            block = fence[1]
            if block.lower().startswith("json"):
                block = block[4:]
            text = block.strip() or text
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]


def build_extractor(
    llm: LLMProvider | None,
    topic: str,
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
        return LLMClaimExtractor(llm, topic, fallback=heuristic)
    return heuristic
