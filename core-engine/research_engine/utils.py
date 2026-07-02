"""Small, dependency-free helpers shared across subsystems."""
from __future__ import annotations

import re
from datetime import datetime, timezone

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9'\-]+")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def utc_now_iso() -> str:
    """Current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def slugify(text: str) -> str:
    """Lowercase, hyphenated slug suitable for ids and filenames."""
    slug = _SLUG_RE.sub("-", text.strip().lower()).strip("-")
    return slug or "untitled"


def safe_filename(text: str) -> str:
    """Turn a topic into a filesystem-safe name, preserving readability.

    Spaces are kept (matching the documented ``<topic>_report.md`` convention);
    path separators and control characters are removed.
    """
    cleaned = text.strip()
    for bad in ("/", "\\", "\0", "\n", "\r", "\t"):
        cleaned = cleaned.replace(bad, "-")
    cleaned = cleaned.strip(". ")
    return cleaned or "untitled"


def domain_of(url: str) -> str:
    """Return the lowercase network domain of a URL, without a leading ``www.``.

    Returns "" for empty input or non-network locators (e.g. ``local://...``,
    file paths). Best-effort and dependency-free (stdlib ``urllib``).
    """
    if not url:
        return ""
    from urllib.parse import urlparse

    netloc = urlparse(url.strip()).netloc.lower()
    if not netloc:
        return ""
    netloc = netloc.split("@")[-1].split(":")[0]  # strip credentials/port
    if netloc.startswith("www."):
        netloc = netloc[4:]
    # A real network domain contains a dot; this rejects non-web locators such as
    # ``local://x/0`` (offline provider) whose "host" is just a slug.
    if "." not in netloc:
        return ""
    return netloc


def split_sentences(text: str) -> list[str]:
    """Split a block of text into trimmed, non-empty sentences."""
    parts = _SENTENCE_RE.split(text.strip())
    return [p.strip() for p in parts if p.strip()]


def normalize_claim(text: str) -> str:
    """Normalize a claim for de-duplication (case/whitespace insensitive)."""
    return re.sub(r"\s+", " ", text.strip().lower()).rstrip(".!?")


def extract_entity_names(text: str, extra_keywords: list[str] | None = None) -> list[str]:
    """Heuristically extract candidate entity names from text.

    Captures multi-word capitalized phrases (e.g. "Quantum Computing") plus any
    supplied domain keywords. This is intentionally simple; a future objective
    can replace it with a real named-entity recognizer behind the same call.
    """
    names: list[str] = []
    seen: set[str] = set()

    # Sequences of capitalized words, ignoring a leading sentence-initial word
    # only when it is a common stopword.
    for match in re.finditer(r"\b([A-Z][A-Za-z0-9'\-]+(?:\s+[A-Z][A-Za-z0-9'\-]+)*)\b", text):
        phrase = match.group(1).strip()
        key = phrase.lower()
        if len(phrase) < 3 or key in _STOPWORDS or key in seen:
            continue
        seen.add(key)
        names.append(phrase)

    for kw in extra_keywords or []:
        key = kw.lower()
        if key not in seen and len(kw) >= 3:
            seen.add(key)
            names.append(kw)
    return names


def keywords(text: str, limit: int = 8) -> list[str]:
    """Return the most salient content words in a topic string."""
    out: list[str] = []
    seen: set[str] = set()
    for match in _WORD_RE.finditer(text):
        word = match.group(0)
        low = word.lower()
        if low in _STOPWORDS or low in seen or len(low) < 3:
            continue
        seen.add(low)
        out.append(word)
        if len(out) >= limit:
            break
    return out


_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for", "with",
    "as", "by", "at", "from", "is", "are", "was", "were", "be", "been", "being",
    "this", "that", "these", "those", "it", "its", "into", "about", "than",
    "then", "there", "their", "they", "them", "we", "you", "your", "our", "not",
    "no", "can", "could", "should", "would", "may", "might", "will", "shall",
    "how", "what", "why", "when", "where", "which", "who", "whom", "overview",
}
