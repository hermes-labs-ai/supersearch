"""Deep-fetch evidence provenance and fallback controls."""

from __future__ import annotations

from datetime import date

import requests

from supersearch import search
from supersearch.verify import nli, pipeline
from supersearch.verify.nli import ClassificationResult
from supersearch.verify.retrieval import Retrieved, RetrievalResult


def _records():
    return [
        Retrieved(
            "Page A", "https://example.org/a", "snippet-A-original", engines=["ddg"]
        ),
        Retrieved(
            "Page B", "https://example.org/b", "snippet-B-original", engines=["bing"]
        ),
    ]


def _patch_retrieval(monkeypatch, records):
    monkeypatch.setattr(
        pipeline,
        "retrieve_with_status",
        lambda *a, **kw: RetrievalResult(records=list(records), status="ok"),
    )
    monkeypatch.setattr(pipeline, "_rerank_for_deep", lambda claim, items: list(items))


def test_deep_success_binds_output_to_fetched_page(monkeypatch):
    records = _records()
    _patch_retrieval(monkeypatch, records)
    page_a = "PAGE-A-CONTENT supports the claim. " * 120
    page_b = "PAGE-B-CONTENT supports the claim. " * 120
    monkeypatch.setattr(
        pipeline,
        "_fetch_one",
        lambda url, max_chars, timeout: page_a if url.endswith("/a") else page_b,
    )
    captured = {}

    def classify(claim, snippets, content_hashes=None):
        captured["snippets"] = list(snippets)
        captured["hashes"] = list(content_hashes or [])
        return [ClassificationResult("ENTAIL", "ok", "fixture") for _ in snippets]

    monkeypatch.setattr(pipeline, "classify_batch_results", classify)
    result = pipeline.verify_claim(
        "PAGE supports the claim", deep=True, as_of=date(2026, 7, 18)
    )

    assert result.verdict == "SUPPORTED"
    assert [source.evidence_kind for source in result.sources] == [
        "fetched_page",
        "fetched_page",
    ]
    assert all(source.fetch_status == "fetched" for source in result.sources)
    assert result.sources[0].evidence_excerpt in captured["snippets"][0]
    assert "snippet-A-original" not in result.sources[0].evidence_excerpt
    assert all(captured["hashes"])


def test_deep_failure_is_explicit_snippet_fallback(monkeypatch):
    records = _records()
    _patch_retrieval(monkeypatch, records)
    monkeypatch.setattr(
        pipeline,
        "_fetch_one",
        lambda url, max_chars, timeout: (
            "REAL PAGE TEXT" if url.endswith("/a") else None
        ),
    )
    captured = {}

    def classify(claim, snippets, content_hashes=None):
        captured["snippets"] = list(snippets)
        return [ClassificationResult("NEUTRAL", "ok", "fixture") for _ in snippets]

    monkeypatch.setattr(pipeline, "classify_batch_results", classify)
    result = pipeline.verify_claim("claim", deep=True, as_of=date(2026, 7, 18))

    first, second = result.sources
    assert (first.evidence_kind, first.fetch_status) == ("fetched_page", "fetched")
    assert (second.evidence_kind, second.fetch_status) == ("search_snippet", "failed")
    assert second.evidence_excerpt == "snippet-B-original"
    assert captured["snippets"][1] == second.search_snippet
    assert any("fell back" in item for item in result.limitations)


def test_fetched_page_negative_control_overrides_entailing_snippet(monkeypatch):
    record = Retrieved(
        "Page",
        "https://example.org/page",
        "The claim is definitely true.",
        engines=["ddg"],
    )
    _patch_retrieval(monkeypatch, [record])
    monkeypatch.setattr(
        pipeline,
        "_fetch_one",
        lambda *a, **kw: "The full page explicitly says the claim is false.",
    )
    monkeypatch.setattr(
        pipeline,
        "classify_batch_results",
        lambda claim, snippets, **kw: [
            ClassificationResult("CONTRADICT", "ok", "fixture")
        ],
    )

    result = pipeline.verify_claim(
        "The claim is true", deep=True, as_of=date(2026, 7, 18)
    )
    assert result.verdict == "CONTRADICTED"
    assert result.sources[0].evidence_kind == "fetched_page"
    assert "false" in result.sources[0].evidence_excerpt
    assert "definitely true" not in result.sources[0].evidence_excerpt


def test_deep_fetch_failures_keep_json_stdout_clean(monkeypatch, capsys):
    def fail(*a, **kw):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(search.requests, "get", fail)
    assert pipeline._deep_fetch_top(_records()) == {}
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Error fetching" in captured.err


def test_cache_key_differs_snippet_vs_deep():
    base = nli._cache_key("claim", "snippet", "model")
    deep = nli._cache_key("claim", "snippet", "model", content_hash="abc123")
    assert base != deep
    assert deep == nli._cache_key("claim", "snippet", "model", content_hash="abc123")
