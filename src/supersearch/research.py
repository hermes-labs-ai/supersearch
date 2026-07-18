"""Fan-out research pipeline for supersearch v0.9.

``run_research(topic, ...)`` composes the v0.7/v0.8 building blocks into a
corpus-writing pipeline:

    expand → route → search_all (parallel over variants)
    → fact_audit (for top entities)
    → optional multi-hop (search_all per top-entity)
    → rerank against topic
    → parallel fetch_content
    → write pages/*.txt, corpus.jsonl, analysis.md, STATUS.md

Composition-only. No new engines, no new dependencies. The pipeline degrades
gracefully — every upstream failure (expand returns [], summarizer down,
fetches fail) produces a usable, partial corpus rather than a crash.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .expand import expand_query
from .fact_audit import audit
from .rerank import LocalReranker
from .routing import route
from .search import DuckDuckGoSearch
from .sources import search_all
from .summarize import summarize_with_ollama

logger = logging.getLogger(__name__)


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str, max_len: int = 64) -> str:
    """ASCII slug for filesystem paths."""
    s = _SLUG_RE.sub("-", (text or "").lower()).strip("-")
    return (s or "research")[:max_len]


def _dedupe_by_url(lists: list[list]) -> list:
    """Flat dedupe preserving first-seen order and the source result's own
    ``sources`` provenance (set by ``search_all``).
    """
    seen: dict = {}
    order: list = []
    for results in lists:
        for r in results or []:
            url = getattr(r, "url", None)
            if not url or url in seen:
                continue
            seen[url] = r
            order.append(url)
    return [seen[u] for u in order]


def _ensure_variants(topic: str, variants: list[str], min_len: int = 3) -> list[str]:
    """Pad ``variants`` with ``topic`` until len >= min_len, no duplicates."""
    out: list[str] = []
    if topic not in variants:
        out.append(topic)
    for v in variants:
        if v and v not in out:
            out.append(v)
    while len(out) < min_len:
        out.append(topic)
    return out


def _search_variants_parallel(
    variants: list[str], max_per_source: int = 3, max_workers: int = 4
) -> dict[str, list]:
    """Run search_all for each variant in parallel. Non-fatal per variant."""
    def _one(v):
        try:
            routed = route(v)
            return v, search_all(v, sources=routed, max_per_source=max_per_source) or []
        except Exception as exc:
            logger.warning("search_all(%r) failed: %s", v, exc)
            return v, []

    out: dict[str, list] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for v, results in pool.map(_one, variants):
            out[v] = results
    return out


def _top_entities(audit_obj, n: int = 5) -> list[tuple[str, int]]:
    """Count entity occurrences across audit.facts, return top-n."""
    counts: dict[str, int] = {}
    for f in audit_obj.facts:
        if f.entity:
            counts[f.entity] = counts.get(f.entity, 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])[:n]


def _multi_hop(
    topic: str, entities: list[str], existing_urls: set, max_workers: int = 4
) -> list:
    """For each entity, run a second-pass query ``"{topic} {entity}"``."""
    if not entities:
        return []

    def _one(entity):
        try:
            q = f"{topic} {entity}"
            routed = route(q)
            return search_all(q, sources=routed, max_per_source=2) or []
        except Exception as exc:
            logger.warning("multi-hop search_all(%r) failed: %s", entity, exc)
            return []

    acc: list = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for results in pool.map(_one, entities):
            for r in results:
                if r.url and r.url not in existing_urls:
                    existing_urls.add(r.url)
                    acc.append(r)
    return acc


def _parallel_fetch(
    records: list, fetcher, max_workers: int, timeout: int
) -> tuple[list[tuple], int]:
    """Fetch each record's URL in a threadpool. Returns (successes, failure_count)."""
    def _one(r):
        try:
            text = fetcher.fetch_content(r.url, timeout=timeout, max_chars=200_000)
            return r, text
        except Exception as exc:
            logger.debug("fetch(%s) failed: %s", r.url, exc)
            return r, None

    successes: list[tuple] = []
    failures = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for r, text in pool.map(_one, records):
            if text and text.strip():
                successes.append((r, text))
            else:
                failures += 1
    return successes, failures


def _write_pages(out_path: Path, successes: list[tuple]) -> None:
    for r, text in successes:
        slug = hashlib.md5(r.url.encode()).hexdigest()[:10]
        variant = getattr(r, "query_variant", "") or ""
        header = f"URL: {r.url}\nTITLE: {r.title or ''}\nVARIANT: {variant}\n\n"
        (out_path / "pages" / f"{slug}.txt").write_text(header + text)


def _write_corpus(out_path: Path, successes: list[tuple]) -> None:
    with (out_path / "corpus.jsonl").open("w") as fh:
        for r, text in successes:
            fh.write(
                json.dumps(
                    {
                        "url": r.url,
                        "title": r.title or "",
                        "snippet": r.snippet or "",
                        "text_len": len(text),
                        "engines": list(getattr(r, "sources", []) or []),
                        "query_variant": getattr(r, "query_variant", "") or "",
                    }
                )
                + "\n"
            )


def _summarize_safe(topic: str, top_reranked: list) -> str:
    """Summarize the top-15 reranked results. Never raise."""
    payload = [
        {"title": r.title or "", "url": r.url, "snippet": r.snippet or ""}
        for r, _ in top_reranked[:15]
    ]
    if not payload:
        return "_No sources available to summarize._"
    try:
        result = summarize_with_ollama(topic, payload, model="qwen3:14b") or {}
        answer = (result.get("answer") or result.get("task") or "").strip()
        return answer or "_Summary empty._"
    except Exception as exc:
        logger.warning("summarizer failed: %s", exc)
        return f"_Summary unavailable: {exc}_"


def _build_analysis_md(
    topic: str,
    summary: str,
    top_entities: list[tuple[str, int]],
    freshness_mean: Optional[float],
    contradictions: list,
    variants: list[str],
    successes: list[tuple],
) -> str:
    """Render the 6-section analysis.md. Order matters — hard gate asserts on it."""
    ents = (
        "\n".join(f"- **{name}** (count: {count})" for name, count in top_entities)
        if top_entities
        else "_No entities detected._"
    )
    fresh = (
        f"{freshness_mean:.2f} (1.0=<30d, 0.5=<1y, 0.0=older/undetected)"
        if freshness_mean is not None
        else "_No dates extracted._"
    )
    cons = (
        "\n".join(
            f"- **{c.entity}** [{c.unit or 'scalar'}]: values={c.values}, span={c.span_ratio:.1%}"
            for c in contradictions
        )
        if contradictions
        else "_None detected (SCOPE: numeric >10% disagreement only)._"
    )
    # Dedupe variants for display only — pipeline still ran each entry.
    seen_vars: list[str] = []
    for v in variants:
        if v not in seen_vars:
            seen_vars.append(v)
    vars_block = "\n".join(f"- `{v}`" for v in seen_vars) or "- `(none)`"
    sources_block = (
        "\n".join(f"- [{(r.title or r.url)}]({r.url})" for r, _ in successes)
        or "_(no sources)_"
    )

    return (
        f"# Research: {topic}\n\n"
        f"## Summary\n\n{summary}\n\n"
        f"## Top Entities\n\n{ents}\n\n"
        f"## Freshness\n\n{fresh}\n\n"
        f"## Contradictions\n\n{cons}\n\n"
        f"## Variants used\n\n{vars_block}\n\n"
        f"## Sources\n\n{sources_block}\n"
    )


def _write_status(
    out_path: Path,
    topic: str,
    variants: list[str],
    merged_count: int,
    attempted: int,
    written: int,
    failures: int,
    wall_seconds: float,
) -> None:
    body = (
        f"# supersearch research — {topic}\n\n"
        f"- timestamp: {datetime.now(timezone.utc).isoformat()}\n"
        f"- topic: {topic}\n"
        f"- variants_count: {len(variants)}\n"
        f"- unique_urls_merged: {merged_count}\n"
        f"- pages_attempted: {attempted}\n"
        f"- pages_written: {written}\n"
        f"- failures: {failures}\n"
        f"- wall_seconds: {wall_seconds:.1f}\n"
        f"- exit_code: 0\n"
    )
    (out_path / "STATUS.md").write_text(body)


def run_research(
    topic: str,
    *,
    depth: int = 1,
    max_pages: int = 50,
    out_dir: str,
    max_workers_fetch: int = 10,
    fetch_timeout: int = 15,
) -> dict:
    """Execute the fan-out research pipeline. Returns a stats dict.

    ``out_dir`` is wiped and recreated. Fetch failures are counted, not fatal.
    Any missing local service (expand/summarizer/embeddings) degrades gracefully
    to a narrower corpus rather than raising.
    """
    start = time.time()
    out_path = Path(out_dir)
    if out_path.exists():
        shutil.rmtree(out_path)
    (out_path / "pages").mkdir(parents=True)

    # 1. Variants
    raw_variants = expand_query(topic, max_variants=6) or []
    variants = _ensure_variants(topic, raw_variants, min_len=3)

    # 2. Parallel search_all per variant
    by_variant = _search_variants_parallel(variants, max_per_source=3)

    # 3. Flatten + dedupe, tag query_variant
    merged = _dedupe_by_url(list(by_variant.values()))
    url_to_variant: dict[str, str] = {}
    for v, results in by_variant.items():
        for r in results or []:
            if r.url and r.url not in url_to_variant:
                url_to_variant[r.url] = v
    for r in merged:
        setattr(r, "query_variant", url_to_variant.get(r.url, topic))

    # 4. Top entities via fact_audit
    audit1 = audit(merged)
    entities = [name for name, _ in _top_entities(audit1, n=5)]

    # 5. Multi-hop
    if depth >= 1 and entities:
        existing_urls = {r.url for r in merged}
        extra = _multi_hop(topic, entities, existing_urls)
        for r in extra:
            setattr(r, "query_variant", f"{topic} +entity")
        merged.extend(extra)

    # 6. Rerank
    try:
        reranked = LocalReranker().rerank(topic, merged)
    except Exception as exc:
        logger.warning("rerank failed (%s); using merge order", exc)
        reranked = [(r, 0.0) for r in merged]

    # 7. Parallel fetch top max_pages
    top_records = [r for r, _ in reranked[:max_pages]]
    fetcher = DuckDuckGoSearch()
    successes, failures = _parallel_fetch(
        top_records, fetcher, max_workers=max_workers_fetch, timeout=fetch_timeout
    )

    # 8-9. Write pages + corpus
    _write_pages(out_path, successes)
    _write_corpus(out_path, successes)

    # 10. Summarize
    summary = _summarize_safe(topic, reranked)

    # 11. Final audit on what we actually fetched
    fetched_records = [r for r, _ in successes]
    audit2 = audit(fetched_records) if fetched_records else audit1

    # 12. analysis.md with exactly 6 sections in order
    analysis_md = _build_analysis_md(
        topic=topic,
        summary=summary,
        top_entities=_top_entities(audit2, n=5) or _top_entities(audit1, n=5),
        freshness_mean=audit2.freshness_mean,
        contradictions=list(audit2.contradictions or []),
        variants=variants,
        successes=successes,
    )
    (out_path / "analysis.md").write_text(analysis_md)

    # 13. STATUS.md
    wall = time.time() - start
    _write_status(
        out_path,
        topic=topic,
        variants=variants,
        merged_count=len(merged),
        attempted=len(top_records),
        written=len(successes),
        failures=failures,
        wall_seconds=wall,
    )

    # 14. Return stats
    return {
        "topic": topic,
        "out_dir": str(out_path),
        "variants_count": len(variants),
        "unique_urls_merged": len(merged),
        "pages_attempted": len(top_records),
        "pages_written": len(successes),
        "failures": failures,
        "wall_seconds": wall,
        "entities": entities,
        "contradictions_count": len(audit2.contradictions or []),
        "freshness_mean": audit2.freshness_mean,
    }
