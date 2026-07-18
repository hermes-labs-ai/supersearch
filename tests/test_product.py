"""Product V1 receipt and agent CLI controls."""

from __future__ import annotations

import json
import sys

import pytest

from supersearch import product, search_cli
from supersearch import __main__ as root_cli
from supersearch.search import SearchResult


def _fake_search_all(
    query,
    *,
    sources,
    max_per_source,
    parallel,
    overall_timeout,
    jitter_max,
    rerank,
    diagnostics,
    source_statuses,
):
    assert query == "useful query"
    assert sources == ["ddg", "github"]
    assert max_per_source == 2
    assert overall_timeout == 4.5
    assert jitter_max == 0.0
    assert rerank is False
    source_statuses.extend(
        [
            {
                "name": "ddg",
                "status": "completed",
                "result_count": 1,
                "diagnostics": [],
            },
            {
                "name": "github",
                "status": "failed",
                "result_count": 0,
                "diagnostics": ["rate limited"],
            },
        ]
    )
    return [
        SearchResult(
            "Useful page",
            "https://example.test/useful",
            "Useful snippet",
            sources=["ddg"],
        )
    ]


def test_product_receipt_is_versioned_partial_and_model_free(monkeypatch):
    monkeypatch.setattr(product, "_source_map", lambda: {"ddg": object, "github": object})
    monkeypatch.setattr(product, "search_all", _fake_search_all)

    receipt = product.search(
        " useful query ",
        sources=["ddg", "github"],
        max_per_source=2,
        deadline_seconds=4.5,
    )

    assert receipt["schema_version"] == "supersearch.search.v1"
    assert receipt["status"] == "partial"
    assert receipt["execution"]["mode"] == "parallel"
    assert receipt["execution"]["deadline_enforced"] is True
    assert receipt["execution"]["llm_required"] is False
    assert receipt["sources"][1]["status"] == "failed"
    assert receipt["results"][0]["sources"] == ["ddg"]
    assert receipt["results"][0]["url"] == "https://example.test/useful"


def test_product_receipt_validates_against_published_schema(monkeypatch):
    from pathlib import Path

    from jsonschema import Draft202012Validator, FormatChecker

    monkeypatch.setattr(product, "_source_map", lambda: {"ddg": object, "github": object})
    monkeypatch.setattr(product, "search_all", _fake_search_all)
    receipt = product.search(
        "useful query",
        sources=["ddg", "github"],
        max_per_source=2,
        deadline_seconds=4.5,
    )
    schema_path = Path(__file__).parents[1] / "docs" / "search-receipt-v1.schema.json"
    schema = json.loads(schema_path.read_text())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(receipt)


def test_nonfinite_optional_score_is_normalized_to_json_null():
    result = SearchResult("t", "https://example.test", "s", score=float("nan"))
    assert product._result_dict(result, 1)["score"] is None


def test_result_dict_normalizes_nullable_third_party_text():
    result = SearchResult(None, "https://example.test", None, sources=["ddg"])
    normalized = product._result_dict(result, 1)
    assert normalized["title"] == ""
    assert normalized["snippet"] == ""
    assert normalized["url"] == "https://example.test"
    assert normalized["sources"] == ["ddg"]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"query": ""}, "non-empty"),
        ({"query": "q", "sources": []}, "at least one"),
        ({"query": "q", "sources": ["ddg", "ddg"]}, "duplicates"),
        ({"query": "q", "sources": ["unknown"]}, "unknown source"),
        ({"query": "q", "max_per_source": 0}, "at least 1"),
        ({"query": "q", "max_per_source": 1.5}, "at least 1"),
        ({"query": "q", "deadline_seconds": 0}, "greater than 0"),
        ({"query": "q", "deadline_seconds": float("nan")}, "finite number"),
        ({"query": "q", "deadline_seconds": float("inf")}, "finite number"),
        ({"query": "q", "deadline_seconds": float("-inf")}, "finite number"),
        ({"query": "q", "deadline_seconds": 3601}, "no more than 3600"),
        ({"query": "q", "rerank": True}, "not supported"),
    ],
)
def test_product_rejects_ambiguous_inputs(monkeypatch, kwargs, message):
    monkeypatch.setattr(
        product,
        "_source_map",
        lambda: {name: object for name in product.DEFAULT_SOURCES},
    )
    with pytest.raises(ValueError, match=message):
        product.search(**kwargs)


def test_cli_stdout_is_exactly_one_json_document(monkeypatch, capsys):
    receipt = {
        "schema_version": "supersearch.search.v1",
        "query": "q",
        "status": "ok",
        "sources": [],
        "results": [],
    }
    monkeypatch.setattr(search_cli, "search", lambda *args, **kwargs: receipt)

    assert search_cli.main(["q", "--pretty"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == receipt
    assert captured.out.count("{\n") == 1


def test_cli_routes_source_stdout_noise_to_stderr(monkeypatch, capsys):
    receipt = {
        "schema_version": "supersearch.search.v1",
        "query": "q",
        "status": "ok",
        "sources": [],
        "results": [],
    }

    def noisy_search(*args, **kwargs):
        print("ADAPTER STDOUT")
        return receipt

    monkeypatch.setattr(search_cli, "search", noisy_search)

    assert search_cli.main(["q"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == receipt
    assert "ADAPTER STDOUT" not in captured.out
    assert "ADAPTER STDOUT" in captured.err


def test_cli_unavailable_receipt_has_distinct_exit(monkeypatch, capsys):
    receipt = {"status": "unavailable"}
    monkeypatch.setattr(search_cli, "search", lambda *args, **kwargs: receipt)

    assert search_cli.main(["q"]) == 3
    assert json.loads(capsys.readouterr().out) == receipt


def test_cli_rejects_nonfinite_deadline_without_emitting_invalid_json(capsys):
    assert search_cli.main(["q", "--deadline", "nan"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "finite number" in captured.err


def test_list_sources_is_machine_readable(monkeypatch, capsys):
    monkeypatch.setattr(search_cli, "available_sources", lambda: ["ddg", "github"])
    assert search_cli.main(["--list-sources"]) == 0
    assert json.loads(capsys.readouterr().out) == {"sources": ["ddg", "github"]}


def test_root_search_flushes_then_uses_hard_process_exit(monkeypatch):
    class HardExit(Exception):
        def __init__(self, code):
            self.code = code

    monkeypatch.setattr(sys, "argv", ["supersearch", "search", "q"])
    monkeypatch.setattr(search_cli, "main", lambda argv: 7)
    monkeypatch.setattr(root_cli.os, "_exit", lambda code: (_ for _ in ()).throw(HardExit(code)))

    with pytest.raises(HardExit) as raised:
        root_cli.main()
    assert raised.value.code == 7
