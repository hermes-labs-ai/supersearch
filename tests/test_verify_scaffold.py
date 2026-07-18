"""T1: scaffold sanity tests — package imports and CLI entry point is wired."""

from __future__ import annotations

import subprocess
import sys
import json

from supersearch import verify as verify_pkg
from supersearch.verify import pipeline
from supersearch.verify.cli import build_parser, main
from supersearch.verify.pipeline import FreshnessSummary, VerifyResult


def test_package_version_is_defined():
    assert isinstance(verify_pkg.__version__, str)
    assert verify_pkg.__version__.count(".") == 2


def test_cli_help_exits_cleanly(capsys):
    parser = build_parser()
    with _expect_systemexit(0):
        parser.parse_args(["--help"])
    captured = capsys.readouterr().out
    assert "supersearch verify" in captured
    assert "SUPPORTED" in captured


def test_cli_no_args_returns_usage_and_exits_2():
    rc = main([])
    assert rc == 2


def test_entrypoint_script_installed():
    """`python -m supersearch verify --version` must work through the CLI dispatch."""
    result = subprocess.run(
        [sys.executable, "-m", "supersearch", "verify", "--version"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "supersearch verify" in result.stdout


def test_root_help_is_a_real_help_path():
    result = subprocess.run(
        [sys.executable, "-m", "supersearch", "--help"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0
    assert result.stdout.startswith("Usage:")
    assert "supersearch search" in result.stdout.splitlines()[0]
    assert "supersearch verify" in result.stdout


def test_max_sources_bounds_are_enforced():
    parser = build_parser()
    for value in ["0", "21", "not-a-number"]:
        with _expect_systemexit(2):
            parser.parse_args(["claim", "--max-sources", value])


def test_real_cli_json_stdout_contract(monkeypatch, capsys):
    fixture = VerifyResult(
        claim="claim",
        verdict="UNVERIFIED",
        verdict_reason="no_sources",
        retrieval_status="no_sources",
        freshness=FreshnessSummary("2026-07-18", 0, 0, None),
    )
    monkeypatch.setattr(pipeline, "verify_claim", lambda *a, **kw: fixture)
    assert main(["claim", "--json", "--no-gates"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    data = json.loads(captured.out)
    assert data["schema_version"] == "supersearch.verify.v1"
    assert data["verdict"] == "UNVERIFIED"


# ---- helpers -----------------------------------------------------------------


class _expect_systemexit:
    """Context manager asserting SystemExit with a given code."""

    def __init__(self, code: int):
        self.code = code

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        assert exc_type is SystemExit, f"expected SystemExit, got {exc_type}"
        assert exc.code == self.code, f"expected exit {self.code}, got {exc.code}"
        return True
