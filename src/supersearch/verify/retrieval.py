"""Retrieval layer: route engines, search, strip HTML, return typed records.

Composition-only wrapper over ``supersearch.sources.search_all``. We do NOT
implement any engine-specific fetching here — every hit comes from the same
deduped, provenance-stamped results SuperSearch already produces.

v0.9: query fan-out. Before retrieval we ask ``supersearch.expand.expand_query``
for 2-3 alternative phrasings and run ``search_all`` for the original claim
plus each variant in parallel. Cross-variant dedup by URL keeps the merged
pool bounded (≤20). Expand failure is non-fatal — we fall back to the base
claim only.
"""

from __future__ import annotations

import html
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Verification must remain usable when Ollama is absent, and its wall-clock
# deadline must not depend on ddgs/primp calls that can monopolize the Python
# process during a stuck socket. These package-owned defaults use connectors
# with explicit requests/httpx timeouts. General ``supersearch`` routing keeps
# its broader model-aware engine policy; callers can still pass ``engines``
# explicitly to this module's public retrieval functions.
VERIFY_DEFAULT_ENGINES = (
    "hn",
    "github",
    "arxiv",
    "semantic_scholar",
    "qwant",
    "ecosia",
    "startpage",
    "marginalia",
    "wiby",
)


# --- HTML stripping -----------------------------------------------------------
#
# Snippets from search engines occasionally carry residual markup: <b>query</b>
# highlights, stray <em>, HTML entities. We're not trying to parse HTML —
# a minimal tag/entity pass is enough and avoids adding a BS4 dependency.

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean(text: str | None) -> str:
    if not text:
        return ""
    stripped = _TAG_RE.sub(" ", text)
    decoded = html.unescape(stripped)
    return _WS_RE.sub(" ", decoded).strip()


# --- Typed output -------------------------------------------------------------


@dataclass
class Retrieved:
    """One retrieval record. Mirrors supersearch SearchResult but HTML-cleaned
    and duck-typed for ``supersearch.fact_audit.extract_facts`` (which reads
    ``.title``, ``.snippet``, ``.url``).

    ``query_variant`` records which expansion variant first surfaced the URL.
    Empty string for the base claim. Populated by the v0.9 fan-out path.
    """

    title: str
    url: str
    snippet: str
    raw_content: str = ""
    engines: list[str] = field(default_factory=list)
    query_variant: str = ""

    def as_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "raw_content": self.raw_content,
            "engines": list(self.engines),
            "query_variant": self.query_variant,
        }


@dataclass(frozen=True)
class SearchAttempt:
    query: str
    ok: bool
    results: list


@dataclass
class RetrievalResult:
    records: list[Retrieved] = field(default_factory=list)
    status: str = "no_sources"  # ok | partial | no_sources | unavailable
    attempted_queries: list[str] = field(default_factory=list)
    failed_queries: list[str] = field(default_factory=list)


# --- Main entry ---------------------------------------------------------------


def _route_engines(_claim: str) -> list[str]:
    """Return package-owned defaults without consulting a local model."""
    return list(VERIFY_DEFAULT_ENGINES)


def _expand_claim(claim: str, max_variants: int = 3) -> list[str]:
    """Wrap ``expand_query`` so tests can monkeypatch this seam directly.

    Returns an empty list on any failure — the caller degrades to base-claim-only
    retrieval without raising.
    """
    try:
        from supersearch.expand import expand_query

        return expand_query(claim, max_variants=max_variants) or []
    except Exception as e:  # pragma: no cover — expand already swallows its own errors
        logger.warning("supersearch.verify: expand_query failed (%s); no variants", e)
        return []


def _search_one_variant(
    query: str,
    engines: list[str] | None,
    max_per_source: int,
    overall_timeout: int,
) -> SearchAttempt:
    """Run one variant and retain structured per-source failure status."""
    raw = []
    raised = False
    diagnostics: list[str] = []
    try:
        from supersearch.sources import search_all

        raw = search_all(
            query,
            sources=engines or None,
            max_per_source=max_per_source,
            parallel=True,
            overall_timeout=overall_timeout,
            diagnostics=diagnostics,
        )
    except Exception as e:
        logger.warning("supersearch.verify: search_all(%r) failed (%s)", query, e)
        raised = True
    return SearchAttempt(
        query=query, ok=not raised and not diagnostics, results=raw or []
    )


def _merge_across_variants(
    results_by_variant: dict[str, list],
    cap: int = 20,
) -> list:
    """Dedupe merged SearchResults across variant runs, preserving engine
    provenance (``result.sources``) and tagging each unique URL with the first
    variant that surfaced it (``result.query_variant``)."""
    by_url: dict = {}
    order: list[str] = []
    for variant_q, results in results_by_variant.items():
        for r in results:
            url = getattr(r, "url", "") or ""
            if not url:
                continue
            if url not in by_url:
                # Tag in place — these are fresh SearchResult instances from search_all.
                try:
                    r.query_variant = variant_q
                except AttributeError:  # dataclass should accept setattr; skip if not
                    pass
                by_url[url] = r
                order.append(url)
            else:
                existing = by_url[url]
                for src in getattr(r, "sources", []) or []:
                    if src not in existing.sources:
                        existing.sources.append(src)
            if len(order) >= cap:
                break
        if len(order) >= cap:
            break
    return [by_url[u] for u in order[:cap]]


def retrieve(
    claim: str,
    max_sources: int = 12,
    engines: list[str] | None = None,
    overall_timeout: int = 25,
    max_per_source: int = 3,
) -> list[Retrieved]:
    """Compatibility wrapper returning only retrieval records."""
    return retrieve_with_status(
        claim,
        max_sources=max_sources,
        engines=engines,
        overall_timeout=overall_timeout,
        max_per_source=max_per_source,
    ).records


def retrieve_with_status(
    claim: str,
    max_sources: int = 12,
    engines: list[str] | None = None,
    overall_timeout: int = 25,
    max_per_source: int = 3,
) -> RetrievalResult:
    """Fetch search results for ``claim`` across intelligence-routed engines.

    v0.9 fan-out: retrieve the base claim AND up to 3 expanded variants in
    parallel, then dedupe the merged pool by URL. Cap at 20 before handing
    back to the caller; further trimmed to ``max_sources``.

    Strips HTML, preserves engine provenance + expansion variant. Returns
    ``[]`` on total failure rather than raising — a verifier that can't fetch
    sources should still emit UNVERIFIED, not crash.
    """
    if engines is None:
        engines = _route_engines(claim)

    variants = _expand_claim(claim, max_variants=3)
    queries: list[str] = [claim] + [v for v in variants if v and v != claim]
    # Deduplicate variant strings while preserving order (claim first).
    seen_q: set[str] = set()
    queries = [q for q in queries if not (q in seen_q or seen_q.add(q))]

    attempts_by_variant: dict[str, SearchAttempt] = {}
    if len(queries) == 1:
        attempts_by_variant[queries[0]] = _search_one_variant(
            queries[0], engines, max_per_source, overall_timeout
        )
    else:
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {
                pool.submit(
                    _search_one_variant, q, engines, max_per_source, overall_timeout
                ): q
                for q in queries
            }
            for fut in as_completed(futures):
                q = futures[fut]
                try:
                    attempts_by_variant[q] = fut.result()
                except Exception as e:
                    logger.warning("supersearch.verify: variant %r failed (%s)", q, e)
                    attempts_by_variant[q] = SearchAttempt(
                        query=q, ok=False, results=[]
                    )
        # Preserve claim-first ordering regardless of completion order.
        attempts_by_variant = {
            q: attempts_by_variant.get(q, SearchAttempt(query=q, ok=False, results=[]))
            for q in queries
        }

    results_by_variant = {
        q: attempt.results for q, attempt in attempts_by_variant.items()
    }
    merged = _merge_across_variants(results_by_variant, cap=20)

    out: list[Retrieved] = []
    seen_urls: set[str] = set()
    for r in merged:
        url = getattr(r, "url", "") or ""
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        out.append(
            Retrieved(
                title=_clean(getattr(r, "title", "")),
                url=url,
                snippet=_clean(getattr(r, "snippet", "")),
                raw_content=_clean(getattr(r, "raw_content", "") or ""),
                engines=list(getattr(r, "sources", []) or []),
                query_variant=getattr(r, "query_variant", "") or "",
            )
        )
        if len(out) >= max_sources:
            break
    failed = [q for q, attempt in attempts_by_variant.items() if not attempt.ok]
    if failed and out:
        status = "partial"
    elif failed:
        status = "unavailable"
    elif out:
        status = "ok"
    else:
        status = "no_sources"
    return RetrievalResult(
        records=out,
        status=status,
        attempted_queries=list(queries),
        failed_queries=failed,
    )
