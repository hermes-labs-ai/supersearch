"""Local re-ranker using Ollama embeddings + freshness + domain authority.

Ranking score is a weighted blend:

    score = W_SEMANTIC * cosine_sim(query, title+snippet)
          + W_FRESHNESS * freshness_signal(text, url)
          + W_AUTHORITY * domain_authority(url)

Weights are tuned toward semantic similarity (the primary signal) with
freshness and authority as tiebreakers. Results with identical snippet bodies
(first 200 chars, normalized) are deduped after scoring — keeping the highest
scored copy.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import requests
import numpy as np

from .search import SearchResult
from .diagnostics import report

W_SEMANTIC = 0.70
W_FRESHNESS = 0.15
W_AUTHORITY = 0.15

# Known-high-quality domains. Authority = 1.0.
# Kept small and hand-curated — this is a signal, not a moat.
_AUTHORITY_TIERS: dict[str, float] = {
    # Research / reference
    "arxiv.org": 1.0,
    "openreview.net": 1.0,
    "semanticscholar.org": 1.0,
    "openalex.org": 1.0,
    "nature.com": 1.0,
    "sciencedirect.com": 0.95,
    "wikipedia.org": 0.95,
    "en.wikipedia.org": 0.95,
    # Primary tech
    "github.com": 0.90,
    "gitlab.com": 0.85,
    "huggingface.co": 0.90,
    "anthropic.com": 0.90,
    "openai.com": 0.90,
    "pytorch.org": 0.85,
    # Reputable press / engineering
    "news.ycombinator.com": 0.75,
    "stackoverflow.com": 0.80,
    "stackexchange.com": 0.80,
    # Docs
    "developer.mozilla.org": 0.95,
    "docs.python.org": 0.95,
}

# Wildcard TLD-based authority hints. Checked after exact-domain.
_TLD_AUTHORITY: tuple[tuple[str, float], ...] = (
    (".gov", 0.85),
    (".edu", 0.80),
    (".ac.uk", 0.80),
)

_YEAR_RE = re.compile(r"\b(19[89]\d|20\d{2})\b")
_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def extract_year(text: str, url: str = "") -> Optional[int]:
    """Find the most recent plausible publication year in ``text`` or ``url``.

    Looks for ISO dates first (most reliable), then any 4-digit year in
    [1980, current+1]. Returns None if nothing found.
    """
    current = datetime.now(timezone.utc).year
    upper = current + 1
    candidates: list[int] = []
    for m in _ISO_DATE_RE.finditer(text or ""):
        try:
            y = int(m.group(1))
            if 1980 <= y <= upper:
                candidates.append(y)
        except ValueError:
            continue
    combined = f"{text or ''} {url or ''}"
    for m in _YEAR_RE.finditer(combined):
        try:
            y = int(m.group(1))
            if 1980 <= y <= upper:
                candidates.append(y)
        except ValueError:
            continue
    return max(candidates) if candidates else None


def freshness_signal(text: str, url: str = "", now_year: Optional[int] = None) -> float:
    """Return a freshness score in [0.0, 1.0].

    - Year == now → 1.0
    - Year == now-1 → 0.85
    - Year == now-2 → 0.70
    - Linearly decays by 0.15/year; clamps at 0.0 after ~7 years.
    - No year found → 0.3 (neutral-ish; unknown age shouldn't dominate).
    """
    if now_year is None:
        now_year = datetime.now(timezone.utc).year
    y = extract_year(text, url)
    if y is None:
        return 0.3
    gap = max(0, now_year - y)
    return max(0.0, 1.0 - gap * 0.15)


def _host(url: str) -> str:
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return ""
    return host.lower()


def domain_authority(url: str) -> float:
    """Return an authority score in [0.0, 1.0] for ``url``.

    Order:
      1. Exact host match in ``_AUTHORITY_TIERS``.
      2. Parent-domain match (e.g. ``en.wikipedia.org`` → ``wikipedia.org``).
      3. Known-good TLD suffix (``.gov``, ``.edu``, ``.ac.uk``).
      4. Default: 0.5 (neutral).
    """
    host = _host(url)
    if not host:
        return 0.5
    if host in _AUTHORITY_TIERS:
        return _AUTHORITY_TIERS[host]
    # Strip leading "www."
    if host.startswith("www."):
        trimmed = host[4:]
        if trimmed in _AUTHORITY_TIERS:
            return _AUTHORITY_TIERS[trimmed]
    # Parent-domain match: walk up the labels.
    parts = host.split(".")
    for i in range(1, len(parts) - 1):
        parent = ".".join(parts[i:])
        if parent in _AUTHORITY_TIERS:
            return _AUTHORITY_TIERS[parent]
    # TLD / suffix matches.
    for suffix, score in _TLD_AUTHORITY:
        if host.endswith(suffix):
            return score
    return 0.5


def snippet_fingerprint(snippet: str, length: int = 200) -> str:
    """Stable hash of a normalized snippet prefix.

    Used to detect near-duplicate snippets surfacing from different URLs
    (content-farm mirrors, scraped aggregators). Normalization lowercases
    and collapses whitespace so minor formatting doesn't break the match.
    """
    if not snippet:
        return ""
    norm = re.sub(r"\s+", " ", snippet.strip().lower())[:length]
    return hashlib.md5(norm.encode("utf-8")).hexdigest()


def dedupe_by_snippet(
    ranked: list[tuple[SearchResult, float]],
) -> list[tuple[SearchResult, float]]:
    """Remove results whose snippet fingerprints have already been seen.

    Iterates in the list order (caller sorts first) so the highest-scored
    copy of duplicated content wins. Results without a snippet are always
    kept (they can't be fingerprinted).
    """
    seen: set[str] = set()
    out: list[tuple[SearchResult, float]] = []
    for r, score in ranked:
        fp = snippet_fingerprint(getattr(r, "snippet", "") or "")
        if not fp:
            out.append((r, score))
            continue
        if fp in seen:
            continue
        seen.add(fp)
        out.append((r, score))
    return out


class LocalReranker:
    """Re-rank search results using local Ollama embeddings + quality signals."""

    def __init__(self, ollama_url: str = "http://localhost:11434"):
        self.ollama_url = ollama_url
        self.model = "nomic-embed-text"

    def _embed(self, text: str) -> Optional[list[float]]:
        try:
            response = requests.post(
                f"{self.ollama_url}/api/embed",
                json={"model": self.model, "input": text},
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            if "embeddings" in data and len(data["embeddings"]) > 0:
                return data["embeddings"][0]
            return None
        except Exception as e:
            report(f"Error embedding text with Ollama: {e}")
            return None

    def _cosine_similarity(self, vec1: list[float], vec2: list[float]) -> float:
        arr1 = np.array(vec1)
        arr2 = np.array(vec2)
        dot_product = np.dot(arr1, arr2)
        norm1 = np.linalg.norm(arr1)
        norm2 = np.linalg.norm(arr2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(dot_product / (norm1 * norm2))

    def _composite_score(
        self,
        semantic: float,
        text: str,
        url: str,
    ) -> float:
        """Blend semantic similarity with freshness and domain authority."""
        fresh = freshness_signal(text, url)
        auth = domain_authority(url)
        return W_SEMANTIC * semantic + W_FRESHNESS * fresh + W_AUTHORITY * auth

    def rerank(
        self,
        query: str,
        results: list[SearchResult],
        dedupe_snippets: bool = True,
    ) -> list[tuple[SearchResult, float]]:
        """Re-rank by composite quality score.

        Args:
            query: The user query.
            results: Candidate SearchResult objects.
            dedupe_snippets: Drop near-duplicate snippet bodies across URLs.

        Returns:
            (result, score) tuples sorted desc by composite score.
        """
        if not results:
            return []

        query_embedding = self._embed(query)
        if query_embedding is None:
            report("Failed to embed query, returning original order")
            # Still apply freshness + authority so the output isn't random.
            fallback: list[tuple[SearchResult, float]] = []
            for r in results:
                text = f"{r.title} {r.snippet}"
                score = self._composite_score(0.0, text, r.url)
                fallback.append((r, score))
            fallback.sort(key=lambda x: x[1], reverse=True)
            if dedupe_snippets:
                fallback = dedupe_by_snippet(fallback)
            return fallback

        reranked: list[tuple[SearchResult, float]] = []
        for r in results:
            text = f"{r.title} {r.snippet}"
            result_embedding = self._embed(text)
            if result_embedding:
                sem = self._cosine_similarity(query_embedding, result_embedding)
            else:
                sem = 0.0
            score = self._composite_score(sem, text, r.url)
            reranked.append((r, score))

        reranked.sort(key=lambda x: x[1], reverse=True)
        if dedupe_snippets:
            reranked = dedupe_by_snippet(reranked)
        return reranked
