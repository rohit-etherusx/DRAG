"""Knowledge builder.

Transforms verified evidence into the knowledge model (``ARCHITECTURE.md``
v0.5): each knowledge update takes the current verified claims and their
evidence and produces the refreshed knowledge model — canonical entities and
the typed evidence graph — that reasoning operates on.

Responsibilities:

* **entity alias merging** — different spellings of the same entity
  ("Transformer", "transformers", "the Transformer's") are canonicalized to
  one name *before* graph construction, so entities stay unique and
  centrality/relationship queries see one node per concept. The canonical
  spelling is the most frequent original (first-seen breaks ties), and merges
  are recorded as entity aliases;
* **graph construction** — delegated to the existing :class:`EvidenceGraph`
  (claims primary; evidence, documents, entities secondary; typed edges), so
  relationships always rest on verified claims and their evidence.

The builder returns the graph rather than mutating research state itself: the
orchestrator writes the result through the state's interface, keeping this
module free of upward dependencies.
"""
from __future__ import annotations

import re

from research_engine.domain.models import Claim, Evidence
from research_engine.knowledge.graph import EvidenceGraph

_ALIAS_STRIP_RE = re.compile(r"[^a-z0-9]+")
#: Minimum stem length for naive plural folding ("cars" -> "car", but "gas"
#: stays "gas" — folding a 3-letter word's trailing 's' mangles too many words).
_MIN_SINGULAR_STEM = 3


class KnowledgeBuilder:
    """Builds the knowledge model from verified claims and evidence."""

    def build(self, claims: list[Claim], evidence: list[Evidence]) -> EvidenceGraph:
        """Return the knowledge graph for ``claims``, entities canonicalized.

        ``claim.entities`` lists are rewritten in place to canonical spellings
        (aliases merged, duplicates dropped) so every downstream consumer —
        graph, importance, curiosity, report — sees one name per concept.
        """
        canonical = _canonical_names(claims)
        for claim in claims:
            merged: list[str] = []
            for name in claim.entities:
                resolved = canonical.get(_alias_key(name), name)
                if resolved and resolved not in merged:
                    merged.append(resolved)
            claim.entities = merged

        graph = EvidenceGraph()
        graph.build(claims, evidence)
        return graph


def _canonical_names(claims: list[Claim]) -> dict[str, str]:
    """Map each alias key to its canonical spelling.

    The canonical spelling of an entity is its most frequent original spelling
    across all claims; ties resolve to the first-seen spelling so the result
    is deterministic.
    """
    spellings: dict[str, dict[str, int]] = {}
    first_seen: dict[str, dict[str, int]] = {}
    order = 0
    for claim in claims:
        for name in claim.entities:
            key = _alias_key(name)
            if not key:
                continue
            counts = spellings.setdefault(key, {})
            counts[name] = counts.get(name, 0) + 1
            first_seen.setdefault(key, {}).setdefault(name, order)
            order += 1

    canonical: dict[str, str] = {}
    for key, counts in spellings.items():
        canonical[key] = max(
            counts,
            key=lambda name: (counts[name], -first_seen[key][name]),
        )
    return canonical


def _alias_key(name: str) -> str:
    """Normalize an entity spelling to its alias identity.

    Lowercases, strips punctuation/possessives, and folds a naive trailing-s
    plural. Deterministic and intentionally conservative — a missed merge is
    recoverable, a wrong merge corrupts the knowledge model.
    """
    key = _ALIAS_STRIP_RE.sub(" ", name.lower()).strip()
    words = []
    for word in key.split():
        if (
            len(word) > _MIN_SINGULAR_STEM
            and word.endswith("s")
            and not word.endswith("ss")
        ):
            word = word[:-1]
        words.append(word)
    return " ".join(words)
