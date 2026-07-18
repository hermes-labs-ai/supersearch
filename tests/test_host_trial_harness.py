"""Controls for the cross-host Product V1 evaluation harness."""

from __future__ import annotations

import json
from pathlib import Path

from product_evaluation import run_host_trials


def _schema() -> dict:
    path = Path(__file__).parents[1] / "product_evaluation" / "host-trial-output.schema.json"
    return json.loads(path.read_text())


def _valid_document(host: str) -> dict:
    return {
        "host": host,
        "queries": [
            {
                "id": query_id,
                "receipt_status": "ok",
                "result_count": 1,
                "source_states": {
                    "ddg": "completed",
                    "hn": "completed",
                    "github": "completed",
                    "arxiv": "completed",
                },
                "useful_result": None,
            }
            for query_id in ("Q1", "Q2", "Q3")
        ],
        "protocol_assessment": {
            "one_json_document_per_call": True,
            "source_failure_explicit": True,
            "bespoke_adapter_needed": False,
        },
        "nonclaim": "discovery only",
    }


def test_host_stdout_validator_accepts_direct_and_claude_envelope():
    schema = _schema()
    codex = _valid_document("codex")
    claude = _valid_document("claude-fable")

    assert run_host_trials._validate_host_stdout(
        "codex", json.dumps(codex), schema
    ) == (True, None)
    assert run_host_trials._validate_host_stdout(
        "claude-fable", json.dumps({"structured_output": claude}), schema
    ) == (True, None)


def test_host_stdout_validator_rejects_malformed_and_duplicate_pack():
    schema = _schema()
    valid, error = run_host_trials._validate_host_stdout("codex", "not-json", schema)
    assert valid is False
    assert "not JSON" in error

    duplicate = _valid_document("codex")
    duplicate["queries"][1]["id"] = "Q1"
    valid, error = run_host_trials._validate_host_stdout(
        "codex", json.dumps(duplicate), schema
    )
    assert valid is False
    assert "exactly Q1, Q2, Q3" in error


def test_host_prompt_shell_quotes_paths_and_query():
    prereg = {
        "configuration": {
            "sources": ["ddg", "github"],
            "max_per_source": 2,
            "deadline_seconds": 4,
        },
        "queries": [
            {"id": "Q1", "query": "what's new", "useful_if": "a result"},
        ],
    }
    prompt = run_host_trials._prompt(
        "codex",
        Path("/tmp/bin with space/supersearch"),
        Path("/tmp/cache with space"),
        prereg,
    )

    assert "SUPERSEARCH_CACHE_DIR='/tmp/cache with space'" in prompt
    assert "'/tmp/bin with space/supersearch' search 'what'\"'\"'s new'" in prompt
