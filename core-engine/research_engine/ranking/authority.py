"""Source authority scoring.

Not every source deserves equal weight: a peer-reviewed paper or an official
standards document is stronger evidence than a personal blog. This module assigns
each :class:`~research_engine.domain.models.Source` a deterministic authority
*tier* and a 0..1 *score*, derived from its network domain (with a fallback to
the provider name). The score is an input to confidence estimation — it does not,
by itself, reject a source (relevance filtering does that).

The mapping is intentionally rule-based and transparent so results are
reproducible and easy to audit or extend. It is domain-agnostic: the tiers
describe *kinds* of sources (encyclopedia, peer-reviewed, official, …), never a
subject area.
"""
from __future__ import annotations

from dataclasses import dataclass

from research_engine.domain.models import Source
from research_engine.utils import domain_of


@dataclass(frozen=True)
class AuthorityTier:
    """A named authority level with a representative 0..1 score."""

    name: str
    score: float


# Ordered from strongest to weakest. Kept small and legible on purpose.
PRIMARY = AuthorityTier("primary / peer-reviewed", 0.95)
OFFICIAL = AuthorityTier("official", 0.90)
EDUCATIONAL = AuthorityTier("educational", 0.75)
ENCYCLOPEDIA = AuthorityTier("encyclopedia", 0.65)
REPUTABLE_MEDIA = AuthorityTier("reputable media", 0.60)
TECHNICAL_BLOG = AuthorityTier("technical blog", 0.40)
UNKNOWN = AuthorityTier("unknown web", 0.40)
PERSONAL_BLOG = AuthorityTier("personal blog", 0.30)
SYNTHETIC = AuthorityTier("synthetic (offline)", 0.20)


class SourceAuthorityScorer:
    """Assigns a deterministic authority tier + score to a source.

    Resolution order: exact/suffix domain rules → domain-suffix heuristics
    (``.gov``/``.edu``) → provider-name fallback → neutral "unknown web".
    """

    #: Exact-or-suffix domain → tier. A rule matches when the source domain
    #: equals the key or ends with ``"." + key``.
    _DOMAIN_TIERS: dict[str, AuthorityTier] = {
        # Peer-reviewed / primary research
        "arxiv.org": PRIMARY,
        "nature.com": PRIMARY,
        "science.org": PRIMARY,
        "sciencedirect.com": PRIMARY,
        "springer.com": PRIMARY,
        "link.springer.com": PRIMARY,
        "ieee.org": PRIMARY,
        "ieeexplore.ieee.org": PRIMARY,
        "acm.org": PRIMARY,
        "dl.acm.org": PRIMARY,
        "pubmed.ncbi.nlm.nih.gov": PRIMARY,
        "ncbi.nlm.nih.gov": PRIMARY,
        "plos.org": PRIMARY,
        "biorxiv.org": PRIMARY,
        "ssrn.com": PRIMARY,
        # Encyclopedia
        "wikipedia.org": ENCYCLOPEDIA,
        "britannica.com": ENCYCLOPEDIA,
        "scholarpedia.org": ENCYCLOPEDIA,
        # Reputable media / reference
        "reuters.com": REPUTABLE_MEDIA,
        "apnews.com": REPUTABLE_MEDIA,
        "bbc.com": REPUTABLE_MEDIA,
        "bbc.co.uk": REPUTABLE_MEDIA,
        "nytimes.com": REPUTABLE_MEDIA,
        "economist.com": REPUTABLE_MEDIA,
        # Personal / technical blog platforms
        "medium.com": PERSONAL_BLOG,
        "substack.com": PERSONAL_BLOG,
        "blogspot.com": PERSONAL_BLOG,
        "wordpress.com": PERSONAL_BLOG,
        "tumblr.com": PERSONAL_BLOG,
        "dev.to": TECHNICAL_BLOG,
        "hashnode.dev": TECHNICAL_BLOG,
    }

    #: Provider-name → tier, used when the domain is unavailable/unrecognised
    #: (e.g. the offline provider, or a source built without a URL).
    _PROVIDER_TIERS: dict[str, AuthorityTier] = {
        "arxiv": PRIMARY,
        "wikipedia": ENCYCLOPEDIA,
    }

    def tier_for(self, source: Source) -> AuthorityTier:
        domain = source.domain or domain_of(source.locator)

        if domain:
            exact = self._DOMAIN_TIERS.get(domain)
            if exact is not None:
                return exact
            for key, tier in self._DOMAIN_TIERS.items():
                if domain.endswith("." + key):
                    return tier
            # Generic TLD-based signals for institutions/governments.
            if domain.endswith(".gov") or ".gov." in domain:
                return OFFICIAL
            if domain.endswith(".edu") or ".edu." in domain or domain.endswith(".ac.uk"):
                return EDUCATIONAL
            if domain.endswith(".org"):
                return REPUTABLE_MEDIA
            return UNKNOWN

        # No usable domain (offline `local://...`, file paths, etc.).
        provider = (source.provider or "").lower()
        for key, tier in self._PROVIDER_TIERS.items():
            if key in provider:
                return tier
        if "offline" in provider or "local" in provider:
            return SYNTHETIC
        return UNKNOWN

    def score(self, source: Source) -> tuple[float, str, str]:
        """Return ``(authority_score, tier_name, domain)`` for ``source``.

        Pure: does not mutate ``source``. The caller stamps the fields (the
        ranker does this) so scoring stays side-effect-free and testable.
        """
        domain = source.domain or domain_of(source.locator)
        tier = self.tier_for(source)
        return tier.score, tier.name, domain
