"""Package-owned, offline receipt integrity gates.

These checks validate internal receipt invariants only. They never shell out,
read an ambient checkout, or contact a URL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

from .pipeline import SCHEMA_VERSION, VerifyResult


@dataclass(frozen=True)
class GateCheck:
    name: str
    ok: bool
    detail: str


@dataclass
class GateResult:
    ok: bool
    checks: list[GateCheck] = field(default_factory=list)


def _check(name: str, ok: bool, detail: str) -> GateCheck:
    return GateCheck(name=name, ok=ok, detail=detail)


def run_reality_gates(result: VerifyResult) -> GateResult:
    """Validate source binding and availability vetoes without external state."""
    allowed_verdicts = {"SUPPORTED", "CONTRADICTED", "CONFLICTING", "UNVERIFIED"}
    checks = [
        _check(
            "schema",
            result.schema_version == SCHEMA_VERSION,
            f"schema_version={result.schema_version}",
        ),
        _check(
            "verdict",
            result.verdict in allowed_verdicts,
            f"verdict={result.verdict}",
        ),
    ]

    source_errors: list[str] = []
    for index, source in enumerate(result.sources):
        parsed = urlparse(source.url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            source_errors.append(f"source[{index}] invalid URL")
        if source.evidence_kind == "search_snippet":
            if source.evidence_excerpt not in source.search_snippet:
                source_errors.append(f"source[{index}] excerpt not in search snippet")
            if source.fetch_status == "fetched":
                source_errors.append(f"source[{index}] snippet marked fetched")
        elif source.evidence_kind == "fetched_page":
            if source.fetch_status != "fetched":
                source_errors.append(
                    f"source[{index}] fetched page lacks fetched status"
                )
        else:
            source_errors.append(f"source[{index}] unknown evidence kind")
        if not source.evidence_sha256 or len(source.evidence_sha256) != 64:
            source_errors.append(f"source[{index}] invalid evidence hash")
    checks.append(
        _check(
            "source_binding",
            not source_errors,
            "; ".join(source_errors) if source_errors else "all sources bound",
        )
    )

    availability_ok = True
    detail = "availability veto satisfied"
    if result.verdict != "UNVERIFIED" and (
        result.retrieval_status != "ok" or result.evaluator_status != "ok"
    ):
        availability_ok = False
        detail = (
            f"positive/conflicting verdict with retrieval={result.retrieval_status}, "
            f"evaluator={result.evaluator_status}"
        )
    if result.verdict != "UNVERIFIED" and not result.sources:
        availability_ok = False
        detail = "positive/conflicting verdict without sources"
    checks.append(_check("availability_veto", availability_ok, detail))

    numeric_errors: list[str] = []
    for index, conflict in enumerate(result.numeric_conflicts):
        urls = {item.get("url") for item in conflict.get("evidence", [])}
        if len(urls - {None}) < 2:
            numeric_errors.append(f"numeric_conflicts[{index}] lacks two URLs")
        if float(conflict.get("span_ratio", 0.0)) <= 0.10:
            numeric_errors.append(f"numeric_conflicts[{index}] does not exceed 10%")
    checks.append(
        _check(
            "numeric_provenance",
            not numeric_errors,
            "; ".join(numeric_errors) if numeric_errors else "numeric signals bound",
        )
    )
    return GateResult(ok=all(item.ok for item in checks), checks=checks)
