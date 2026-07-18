"""Stable Product V1 search receipt.

This module is intentionally thin. Retrieval remains in :mod:`supersearch.sources`;
the product seam validates inputs and converts that machinery into one versioned,
failure-explicit document suitable for a CLI, Python caller, or generic agent.
"""

from __future__ import annotations

from datetime import datetime, timezone
import math
import time
from typing import Any

from .sources import DEFAULT_PARALLEL_TIMEOUT, _source_map, search_all

SCHEMA_VERSION = "supersearch.search.v1"
DEFAULT_SOURCES = ("ddg", "hn", "github", "arxiv")
DDGS_CACHE_TTL_SECONDS = 24 * 60 * 60
MAX_DEADLINE_SECONDS = 60 * 60


def available_sources() -> list[str]:
    """Return registered source names in deterministic order."""

    return list(_source_map())


def _validate(
    query: str,
    sources: list[str],
    max_per_source: int,
    deadline_seconds: float,
) -> None:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    if not sources:
        raise ValueError("at least one source is required")
    if len(sources) != len(set(sources)):
        raise ValueError("sources must not contain duplicates")
    unknown = [name for name in sources if name not in _source_map()]
    if unknown:
        raise ValueError(
            "unknown source(s): "
            + ", ".join(unknown)
            + "; use available_sources() or --list-sources"
        )
    if (
        isinstance(max_per_source, bool)
        or not isinstance(max_per_source, int)
        or max_per_source < 1
    ):
        raise ValueError("max_per_source must be at least 1")
    if (
        isinstance(deadline_seconds, bool)
        or not isinstance(deadline_seconds, (int, float))
        or not math.isfinite(deadline_seconds)
        or deadline_seconds <= 0
        or deadline_seconds > MAX_DEADLINE_SECONDS
    ):
        raise ValueError(
            "deadline_seconds must be a finite number greater than 0 "
            f"and no more than {MAX_DEADLINE_SECONDS}"
        )


def _result_dict(result: Any, rank: int) -> dict[str, Any]:
    def text(value: Any) -> str:
        if value is None:
            return ""
        try:
            return str(value)
        except Exception:
            return ""

    score = getattr(result, "score", None)
    if score is not None:
        try:
            score = float(score)
        except (TypeError, ValueError, OverflowError):
            score = None
        if score is not None and not math.isfinite(score):
            score = None
    return {
        "rank": rank,
        "title": text(getattr(result, "title", None)),
        "url": text(getattr(result, "url", None)),
        "snippet": text(getattr(result, "snippet", None)),
        "sources": [
            normalized
            for source in (getattr(result, "sources", None) or [])
            if (normalized := text(source))
        ],
        "score": score,
    }


def search(
    query: str,
    *,
    sources: list[str] | tuple[str, ...] | None = None,
    max_per_source: int = 3,
    deadline_seconds: float = DEFAULT_PARALLEL_TIMEOUT,
    parallel: bool = True,
    rerank: bool = False,
) -> dict[str, Any]:
    """Search public sources and return a versioned, source-explicit receipt.

    This deadline-bounded surface performs retrieval only: it does not
    instantiate a hosted or local LLM and does not require a paid API key.
    Local reranking remains an experimental legacy capability because its model
    calls are not yet governed by this receipt's total deadline.
    """

    requested = list(DEFAULT_SOURCES if sources is None else sources)
    _validate(query, requested, max_per_source, deadline_seconds)
    if rerank:
        raise ValueError(
            "rerank is not supported by the deadline-bounded Product V1 surface"
        )

    source_statuses: list[dict] = []
    diagnostics: list[str] = []
    started = time.monotonic()
    retrieved_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    results = search_all(
        query.strip(),
        sources=requested,
        max_per_source=max_per_source,
        parallel=parallel,
        overall_timeout=deadline_seconds,
        jitter_max=0.0,
        rerank=False,
        diagnostics=diagnostics,
        source_statuses=source_statuses,
    )
    duration_ms = round((time.monotonic() - started) * 1000, 3)

    problem_states = {"degraded", "failed", "timed_out", "unsupported"}
    has_problem = any(item["status"] in problem_states for item in source_statuses)
    if results and has_problem:
        status = "partial"
    elif results:
        status = "ok"
    elif has_problem:
        status = "unavailable"
    else:
        status = "no_results"

    return {
        "schema_version": SCHEMA_VERSION,
        "query": query.strip(),
        "status": status,
        "retrieved_at": retrieved_at,
        "execution": {
            "mode": "parallel" if parallel else "serial",
            "deadline_seconds": deadline_seconds,
            "deadline_enforced": parallel,
            "duration_ms": duration_ms,
            "rerank_requested": False,
            "llm_required": False,
        },
        "cache": {
            "policy": "source_default",
            "ddgs_ttl_seconds": DDGS_CACHE_TTL_SECONDS,
            "note": "DDGS-backed retrieval may use the local cache; direct sources are not cached by the fan-out orchestrator.",
        },
        "sources": source_statuses,
        "result_count": len(results),
        "results": [_result_dict(result, i) for i, result in enumerate(results, 1)],
    }
