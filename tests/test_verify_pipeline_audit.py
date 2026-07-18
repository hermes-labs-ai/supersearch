"""Verdict availability, numeric conflict, freshness, and determinism matrix."""

from __future__ import annotations

from datetime import date

from supersearch.verify import pipeline
from supersearch.verify.formatter import format_json
from supersearch.verify.nli import ClassificationResult
from supersearch.verify.retrieval import Retrieved, RetrievalResult


AS_OF = date(2026, 7, 18)


def _record(title, url, snippet):
    return Retrieved(
        title=title, url=url, snippet=snippet, engines=["ddg"], query_variant="claim"
    )


def _wire(monkeypatch, records, labels, statuses=None, retrieval_status="ok"):
    monkeypatch.setattr(
        pipeline,
        "retrieve_with_status",
        lambda *a, **kw: RetrievalResult(
            records=list(records), status=retrieval_status
        ),
    )
    statuses = statuses or ["ok"] * len(labels)
    monkeypatch.setattr(
        pipeline,
        "classify_batch_results",
        lambda claim, snippets, **kw: [
            ClassificationResult(label, status, "fixture")
            for label, status in zip(labels, statuses, strict=True)
        ],
    )


def test_numeric_conflict_flips_operational_evaluator_to_conflicting(monkeypatch):
    records = [
        _record("Alpha AI", "https://a.example.org", "Alpha AI raised 100M."),
        _record("Alpha AI", "https://b.example.org", "Alpha AI raised 130M."),
    ]
    _wire(monkeypatch, records, ["ENTAIL", "ENTAIL"])
    result = pipeline.verify_claim("Alpha AI raised 100M", as_of=AS_OF)
    assert result.verdict == "CONFLICTING"
    assert result.verdict_reason == "numeric_conflict"
    assert len(result.numeric_conflicts) == 1
    assert len({item["url"] for item in result.numeric_conflicts[0]["evidence"]}) == 2
    snippets = {record.url: record.snippet for record in records}
    assert all(
        item["evidence_excerpt"] in snippets[item["url"]]
        for item in result.numeric_conflicts[0]["evidence"]
    )


def test_numeric_signal_cannot_override_unavailable_evaluator(monkeypatch):
    records = [
        _record("Alpha AI", "https://a.example.org", "Alpha AI raised 100M."),
        _record("Alpha AI", "https://b.example.org", "Alpha AI raised 130M."),
    ]
    _wire(
        monkeypatch,
        records,
        ["NEUTRAL", "NEUTRAL"],
        statuses=["model_unavailable", "model_unavailable"],
    )
    result = pipeline.verify_claim("Alpha AI raised 100M", as_of=AS_OF)
    assert result.verdict == "UNVERIFIED"
    assert result.verdict_reason == "evaluator_unavailable"
    assert result.numeric_conflicts


def test_partial_model_failure_vetoes_positive_verdict(monkeypatch):
    records = [
        _record("A", "https://a.example.org", "The claim is true."),
        _record("B", "https://b.example.org", "More context."),
    ]
    _wire(
        monkeypatch,
        records,
        ["ENTAIL", "NEUTRAL"],
        statuses=["ok", "model_unavailable"],
    )
    result = pipeline.verify_claim("The claim is true", as_of=AS_OF)
    assert result.verdict == "UNVERIFIED"
    assert result.evaluator_status == "partial"


def test_partial_retrieval_vetoes_positive_verdict(monkeypatch):
    records = [_record("A", "https://a.example.org", "The claim is true.")]
    _wire(monkeypatch, records, ["ENTAIL"], retrieval_status="partial")
    result = pipeline.verify_claim("The claim is true", as_of=AS_OF)
    assert result.verdict == "UNVERIFIED"
    assert result.verdict_reason == "retrieval_unavailable"


def test_default_provenance_and_long_excerpt_are_literal(monkeypatch):
    long_snippet = (
        ("prefix " * 80) + "The claim is true near this anchor. " + ("suffix " * 80)
    )
    records = [_record("Long", "https://a.example.org", long_snippet)]
    _wire(monkeypatch, records, ["ENTAIL"])

    result = pipeline.verify_claim("The claim is true", as_of=AS_OF)

    source = result.sources[0]
    assert source.evidence_kind == "search_snippet"
    assert source.fetch_status == "not_requested"
    assert source.evidence_excerpt in source.search_snippet
    assert len(source.evidence_excerpt) <= pipeline.EVIDENCE_EXCERPT_CHARS
    assert not source.evidence_excerpt.endswith("...")
    assert source.engines == ["ddg"]
    assert source.query_variant == "claim"


def test_no_sources_and_retrieval_unavailable_are_unverified(monkeypatch):
    for status, reason in [
        ("no_sources", "no_sources"),
        ("unavailable", "retrieval_unavailable"),
    ]:
        monkeypatch.setattr(
            pipeline,
            "retrieve_with_status",
            lambda *a, _status=status, **kw: RetrievalResult(
                records=[], status=_status
            ),
        )
        result = pipeline.verify_claim("claim", as_of=AS_OF)
        assert result.verdict == "UNVERIFIED"
        assert result.verdict_reason == reason
        assert result.sources == []


def test_exact_ten_percent_and_single_url_do_not_signal_conflict(monkeypatch):
    cases = [
        [
            _record("Alpha AI", "https://a.example.org", "Alpha AI raised 100M."),
            _record("Alpha AI", "https://b.example.org", "Alpha AI raised 110M."),
        ],
        [
            _record("Alpha AI", "https://same.example.org", "Alpha AI raised 100M."),
            _record("Alpha AI", "https://same.example.org", "Alpha AI raised 140M."),
        ],
    ]
    for records in cases:
        _wire(monkeypatch, records, ["ENTAIL", "ENTAIL"])
        result = pipeline.verify_claim("Alpha AI raised funding", as_of=AS_OF)
        assert result.verdict == "SUPPORTED"
        assert result.numeric_conflicts == []


def test_same_url_outlier_does_not_create_cross_url_conflict(monkeypatch):
    records = [
        _record(
            "Alpha AI",
            "https://a.example.org",
            "Alpha AI raised 100M and later revised its own figure to 130M.",
        ),
        _record("Alpha AI", "https://b.example.org", "Alpha AI raised 100M."),
    ]
    _wire(monkeypatch, records, ["ENTAIL", "ENTAIL"])

    result = pipeline.verify_claim("Alpha AI raised funding", as_of=AS_OF)

    assert result.verdict == "SUPPORTED"
    assert result.numeric_conflicts == []


def test_freshness_has_fixed_coverage_and_ignores_future_dates(monkeypatch):
    records = [
        _record("Dated", "https://a.example.org", "Published 2026-07-10: claim."),
        _record("Future", "https://b.example.org", "Published 2027-01-01: claim."),
    ]
    _wire(monkeypatch, records, ["NEUTRAL", "NEUTRAL"])
    result = pipeline.verify_claim("claim", as_of=AS_OF)
    assert result.freshness.as_of == "2026-07-18"
    assert result.freshness.dated_sources == 1
    assert result.freshness.total_sources == 2
    assert result.freshness.mean == 1.0
    assert result.sources[1].date is None


def test_fixed_inputs_produce_byte_identical_json(monkeypatch):
    records = [_record("A", "https://a.example.org", "Published 2026-07-10: claim.")]
    _wire(monkeypatch, records, ["ENTAIL"])
    first = format_json(pipeline.verify_claim("claim", as_of=AS_OF))
    second = format_json(pipeline.verify_claim("claim", as_of=AS_OF))
    assert first == second
