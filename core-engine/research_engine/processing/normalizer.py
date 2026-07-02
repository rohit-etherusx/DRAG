"""Claim normalization.

Different wordings describing an identical fact must become one canonical claim
*before* verification (``OBJECTIVE.md`` module 6) — otherwise the same
assertion phrased two ways would be counted as two claims and corroboration
would be under-measured.

Normalization is deterministic: each claim is reduced to a signature (its
sorted content words, minus stopwords and punctuation), and claims with the
same signature are merged into one canonical :class:`Claim`. The most detailed
wording becomes the canonical text; the other wordings are preserved as
variants; evidence, source, subquestion, and entity references are unioned so
provenance is never lost. Deeper, fuzzy equivalence (paraphrases with different
vocabulary) is handled by the verification engine's clustering stage.
"""
from __future__ import annotations

import re

from research_engine.domain.models import Claim, ClaimType, Evidence
from research_engine.processing.extraction import ExtractedClaim

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9'\-]*")
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "as",
    "by", "at", "from", "is", "are", "was", "were", "be", "been", "being",
    "this", "that", "these", "those", "it", "its", "into", "also", "such",
    "which", "can", "may", "has", "have", "had", "but", "than", "then", "there",
}


class ClaimNormalizer:
    """Merges equivalent claim wordings into canonical claims (deterministic)."""

    def normalize(
        self, extracted: list[ExtractedClaim], evidence_by_id: dict[str, Evidence]
    ) -> list[Claim]:
        """Return canonical claims for ``extracted``, in first-seen order.

        ``evidence_by_id`` supplies each claim's source/subquestion provenance
        via the evidence passage it was extracted from.
        """
        merged: dict[str, Claim] = {}
        order: list[str] = []
        for raw in extracted:
            text = raw.text.strip()
            signature = _signature(text)
            if not signature:
                continue
            claim = merged.get(signature)
            if claim is None:
                claim = Claim(id="", text=text, claim_type=raw.claim_type)
                merged[signature] = claim
                order.append(signature)
            else:
                self._merge_wording(claim, text)
                # FACT is the least specific type: let any specific type win.
                if claim.claim_type is ClaimType.FACT:
                    claim.claim_type = raw.claim_type
            _extend_unique(claim.entities, raw.entities)
            self._attach_provenance(claim, raw, evidence_by_id)

        claims: list[Claim] = []
        for index, signature in enumerate(order, start=1):
            claim = merged[signature]
            claim.id = f"claim-{index}"
            claims.append(claim)
        return claims

    @staticmethod
    def _merge_wording(claim: Claim, text: str) -> None:
        """Keep the most detailed wording canonical; preserve the rest as variants."""
        if text == claim.text:
            return
        if len(text) > len(claim.text):
            if claim.text not in claim.variants:
                claim.variants.append(claim.text)
            claim.text = text
        elif text not in claim.variants:
            claim.variants.append(text)

    @staticmethod
    def _attach_provenance(
        claim: Claim, raw: ExtractedClaim, evidence_by_id: dict[str, Evidence]
    ) -> None:
        if raw.evidence_id and raw.evidence_id not in claim.evidence_ids:
            claim.evidence_ids.append(raw.evidence_id)
        evidence = evidence_by_id.get(raw.evidence_id)
        if evidence is None:
            return
        _extend_unique(claim.source_ids, [evidence.source_id])
        _extend_unique(claim.subquestion_ids, [evidence.subquestion_id])


def _signature(text: str) -> str:
    """Order-insensitive content signature used to detect equivalent wordings."""
    tokens = sorted(
        {
            t for t in _TOKEN_RE.findall(text.lower())
            if len(t) >= 2 and t not in _STOPWORDS
        }
    )
    return " ".join(tokens)


def _extend_unique(target: list[str], items: list[str]) -> None:
    for item in items:
        if item and item not in target:
            target.append(item)
