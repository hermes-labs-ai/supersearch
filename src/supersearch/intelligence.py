"""Intelligence-layer helpers: category-routed search core used by CLI + tests.

``run_search_core`` is the narrow, testable seam between the CLI flags and the
existing search/rerank plumbing. Call it directly from tests to exercise
intelligence-on vs intelligence-off without invoking the full CLI.
"""

from __future__ import annotations

from typing import Optional


def run_search_core(
    query: str,
    intelligence: bool = False,
    max_per_source: int = 3,
    sources_override: Optional[list[str]] = None,
) -> dict:
    """Run a search → rerank → format pipeline and return a JSON-ready dict.

    Args:
        query: User query.
        intelligence: If True, pick engines via ``routing.route(query)``.
            If False, use the default ``search_all`` source set.
        max_per_source: Per-engine result cap.
        sources_override: Bypass routing and use these engines directly.
            Mostly used by tests that stub the source layer.

    Returns:
        ``{query, total_results, intelligence, sources_queried, results}``.
    """
    from .sources import search_all
    from .rerank import LocalReranker
    from .__main__ import format_result

    if sources_override is not None:
        sources = sources_override
    elif intelligence:
        from . import routing
        sources = routing.route(query)
    else:
        sources = None  # search_all's default

    raw = search_all(query, sources=sources, max_per_source=max_per_source)

    reranker = LocalReranker()
    reranked = reranker.rerank(query, raw)
    formatted = [format_result(r, i) for i, r in enumerate(reranked, 1)]

    return {
        "query": query,
        "total_results": len(reranked),
        "intelligence": intelligence,
        "sources_queried": sources if sources is not None else ["<default>"],
        "results": formatted,
    }
