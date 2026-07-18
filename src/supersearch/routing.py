"""Query-to-engine routing via category cosine similarity.

Implements the routing rules defined in ``SCOPE.md``:

- Cosine threshold: 0.7
- If a category scores ≥0.7: route to the top-3 engines for that category
- If 2+ categories score ≥0.7: union top-2 from each, dedupe, cap at 5
- If no category clears the threshold: fall back to ALL engines

The default embedder uses Ollama's ``nomic-embed-text`` via ``LocalReranker``.
Tests inject a deterministic ``embed_fn`` so they never touch the network.
"""

from __future__ import annotations

from typing import Callable, Optional

import numpy as np


# Engine-to-category map. Order within each list is priority order per SCOPE.md.
CATEGORY_ENGINES: dict[str, list[str]] = {
    "academic": ["arxiv", "semantic_scholar"],
    "company": ["github", "searxng"],
    "security": ["github", "hackernews", "searxng"],
    "news": ["hackernews", "twitter", "searxng"],
    "general": ["qwant", "ecosia", "startpage", "marginalia", "searxng", "wiby"],
}

# Category descriptor seeds used for cosine similarity scoring. These are
# exemplar-style descriptions — the query embedding is compared against each
# seed's embedding. Richer seeds produce better separation on nomic-embed-text
# (short seeds cluster at ~0.4–0.6 and rarely cross the 0.7 threshold).
CATEGORY_SEEDS: dict[str, str] = {
    "academic": (
        "academic research paper published in a peer-reviewed journal. "
        "Abstract, methodology, results, citations. Examples: arxiv preprint, "
        "conference proceedings, scholarly article about neural networks, "
        "machine learning theory."
    ),
    "company": (
        "a company, startup, or business. Product launch, funding round, "
        "acquisition, enterprise software vendor, SaaS platform."
    ),
    "security": (
        "security vulnerability, CVE, exploit, patch, breach, incident "
        "response, infosec disclosure, remote code execution."
    ),
    "news": (
        "breaking news today, latest announcement, recent update, press "
        "release, current event, what happened this week."
    ),
    "general": (
        "general reference, encyclopedia entry, how-to tutorial, "
        "explanation, definition, overview of a topic."
    ),
}

COSINE_THRESHOLD = 0.7
TOP_K_SINGLE = 3   # single-category match: take top-3 engines
TOP_K_MULTI = 2    # multi-category match: take top-2 from each
MAX_ENGINES = 5    # cap when unioning across categories


def _cosine(a: list[float], b: list[float]) -> float:
    av = np.asarray(a, dtype=float)
    bv = np.asarray(b, dtype=float)
    na = np.linalg.norm(av)
    nb = np.linalg.norm(bv)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(av, bv) / (na * nb))


def _default_embedder() -> Callable[[str], Optional[list[float]]]:
    """Return the Ollama-backed embedder. Factored so tests can skip it."""
    from .rerank import LocalReranker

    reranker = LocalReranker()
    return reranker._embed


def score_categories(
    query: str,
    embed_fn: Optional[Callable[[str], Optional[list[float]]]] = None,
) -> dict[str, float]:
    """Return {category: cosine_similarity} for ``query`` vs each category seed.

    Any category whose seed fails to embed is omitted. If the query itself
    fails to embed, returns an empty dict (caller treats as fallback).
    """
    embed = embed_fn or _default_embedder()
    q_vec = embed(query)
    if q_vec is None:
        return {}
    scores: dict[str, float] = {}
    for cat, seed in CATEGORY_SEEDS.items():
        seed_vec = embed(seed)
        if seed_vec is None:
            continue
        scores[cat] = _cosine(q_vec, seed_vec)
    return scores


def _all_engines() -> list[str]:
    """Deterministic union of every engine across all categories."""
    seen: list[str] = []
    for engines in CATEGORY_ENGINES.values():
        for e in engines:
            if e not in seen:
                seen.append(e)
    return seen


# -----------------------------------------------------------------------------
# Reachability filter — down-weights self-hosted engines that aren't running.
# -----------------------------------------------------------------------------
#
# Some engines in ``CATEGORY_ENGINES`` assume a locally-running service
# (currently just SearXNG at localhost:8888). Probing once per process lets the
# router skip an engine that's down without editing the category map — when
# the service is restored, no code change is needed.
#
# Tests that need to exercise the raw routing logic should monkeypatch
# ``_UNREACHABLE`` to an empty set to bypass the probe.

_REACHABILITY_PROBES: dict[str, tuple[str, int]] = {
    "searxng": ("localhost", 8888),
}
_UNREACHABLE: Optional[set[str]] = None


def _probe_unreachable(timeout: float = 0.3) -> set[str]:
    """TCP-connect probe each self-hosted engine; return names that refuse."""
    import socket

    down: set[str] = set()
    for name, (host, port) in _REACHABILITY_PROBES.items():
        try:
            with socket.create_connection((host, port), timeout=timeout):
                pass
        except OSError:
            down.add(name)
    return down


def _get_unreachable() -> set[str]:
    """Lazy cache for the reachability probe result."""
    global _UNREACHABLE
    if _UNREACHABLE is None:
        _UNREACHABLE = _probe_unreachable()
    return _UNREACHABLE


def _filter_unreachable(engines: list[str]) -> list[str]:
    down = _get_unreachable()
    if not down:
        return engines
    return [e for e in engines if e not in down]


def route(
    query: str,
    embed_fn: Optional[Callable[[str], Optional[list[float]]]] = None,
    threshold: float = COSINE_THRESHOLD,
) -> list[str]:
    """Return the ordered engine list to query per SCOPE.md routing rules.

    ``embed_fn`` is injectable so tests can run deterministically without Ollama.
    Unreachable self-hosted engines (e.g. SearXNG when the local service is
    down) are filtered after routing — they stay in ``CATEGORY_ENGINES`` so
    restoring the service is a zero-code change.
    """
    scores = score_categories(query, embed_fn=embed_fn)
    above = {c: s for c, s in scores.items() if s >= threshold}

    if not above:
        return _filter_unreachable(_all_engines())

    if len(above) == 1:
        cat = next(iter(above))
        return _filter_unreachable(list(CATEGORY_ENGINES[cat][:TOP_K_SINGLE]))

    # Multi-category: union top-K from each (ordered by descending score),
    # dedupe preserving first-seen order, cap at MAX_ENGINES.
    ordered_cats = sorted(above.items(), key=lambda kv: kv[1], reverse=True)
    merged: list[str] = []
    for cat, _score in ordered_cats:
        for engine in CATEGORY_ENGINES[cat][:TOP_K_MULTI]:
            if engine not in merged:
                merged.append(engine)
            if len(merged) >= MAX_ENGINES:
                return _filter_unreachable(merged)
    return _filter_unreachable(merged)
