"""Versioned JSON schema and legible markdown receipt tests."""

from __future__ import annotations

import json

from supersearch.verify.formatter import format_json, format_markdown
from supersearch.verify.pipeline import FreshnessSummary, SourceVerdict, VerifyResult


def _source(kind="search_snippet", fetch="not_requested"):
    snippet = "A report says Alpha raised 100M in 2025."
    return SourceVerdict(
        url="https://example.org/report",
        title="Alpha report",
        engines=["ddg"],
        query_variant="Alpha raised 100M",
        search_snippet=snippet,
        evidence_kind=kind,
        fetch_status=fetch,
        evidence_excerpt=snippet,
        evidence_sha256="a" * 64,
        nli_label="ENTAIL",
        nli_status="ok",
        date="2025-01-01T00:00:00+00:00",
        date_basis=kind,
        freshness_score=0.0,
    )


def _sample_result():
    return VerifyResult(
        claim="Alpha raised 100M",
        verdict="SUPPORTED",
        verdict_reason="entailment_dominant",
        retrieval_status="ok",
        evaluator_status="ok",
        sources=[_source()],
        freshness=FreshnessSummary("2026-07-18", 1, 1, 0.0),
        engines_used=["ddg"],
        limitations=["Search snippet evidence was not page-verified."],
    )


def test_json_schema_has_exact_stable_top_level_keys():
    data = json.loads(format_json(_sample_result()))
    assert list(data) == [
        "schema_version",
        "claim",
        "verdict",
        "verdict_reason",
        "retrieval_status",
        "evaluator_status",
        "deep_requested",
        "sources",
        "numeric_conflicts",
        "freshness",
        "engines_used",
        "limitations",
        "nonclaims",
        "cost_usd",
    ]
    assert data["schema_version"] == "supersearch.verify.v1"
    assert set(data["sources"][0]) == {
        "url",
        "title",
        "engines",
        "query_variant",
        "search_snippet",
        "evidence_kind",
        "fetch_status",
        "evidence_excerpt",
        "evidence_sha256",
        "nli_label",
        "nli_status",
        "date",
        "date_basis",
        "freshness_score",
    }


def test_markdown_surfaces_provenance_status_limits_and_nonclaims():
    output = format_markdown(_sample_result())
    assert "SUPPORTED" in output
    assert "search_snippet" in output
    assert "not_requested" in output
    assert "example.org/report" in output
    assert "## Limits" in output
    assert "## Nonclaims" in output
    assert "ground truth" in output


def test_empty_unverified_receipt_formats_cleanly():
    result = VerifyResult(
        claim="unknown",
        verdict="UNVERIFIED",
        verdict_reason="no_sources",
        retrieval_status="no_sources",
        freshness=FreshnessSummary("2026-07-18", 0, 0, None),
    )
    assert "No sources retrieved" in format_markdown(result)
    assert json.loads(format_json(result))["verdict"] == "UNVERIFIED"


def test_machine_excerpt_has_no_presentation_mutation():
    result = _sample_result()
    data = json.loads(format_json(result))
    assert data["sources"][0]["evidence_excerpt"] == result.sources[0].search_snippet
