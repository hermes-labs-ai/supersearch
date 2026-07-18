"""Research CLI subcommand + package-owned local-gate wiring."""

from __future__ import annotations

import sys

import pytest

from supersearch import research_cli


def test_help_exits_clean(capsys):
    """`supersearch research --help` must exit 0 and print usage."""
    with pytest.raises(SystemExit) as exc:
        research_cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "research" in out.lower()
    assert "--depth" in out
    assert "--max-pages" in out


def test_smoke_via_monkeypatched_run_research(tmp_path, monkeypatch, capsys):
    """End-to-end CLI smoke without network or external gate scripts."""
    out_dir = tmp_path / "out"

    def fake_run_research(
        topic, *, depth, max_pages, out_dir, max_workers_fetch, fetch_timeout
    ):
        from pathlib import Path

        d = Path(out_dir)
        d.mkdir(parents=True, exist_ok=True)
        # The package-owned local gate validates this stable section order.
        (d / "analysis.md").write_text(
            "# Research: smoke\n\n## Summary\n\nokay\n\n"
            "## Top Entities\n\n- X\n\n"
            "## Freshness\n\n_n/a_\n\n"
            "## Contradictions\n\n_none_\n\n"
            "## Variants used\n\n- smoke\n\n"
            "## Sources\n\n- https://example.com/x\n"
        )
        return {
            "topic": topic,
            "out_dir": str(d),
            "variants_count": 3,
            "unique_urls_merged": 1,
            "pages_attempted": 1,
            "pages_written": 1,
            "failures": 0,
            "wall_seconds": 0.01,
        }

    monkeypatch.setattr(research_cli, "run_research", fake_run_research)
    rc = research_cli.main(["smoke", "--depth=0", "--max-pages=3", f"--out={out_dir}"])
    assert rc == 0
    assert (out_dir / "analysis.md").is_file()
    captured = capsys.readouterr().out
    assert "Wrote corpus" in captured


def test_no_gates_skips_reality_checks(tmp_path, monkeypatch):
    """--no-gates must short-circuit the gate calls entirely."""
    out_dir = tmp_path / "out"

    def fake_run_research(
        topic, *, depth, max_pages, out_dir, max_workers_fetch, fetch_timeout
    ):
        from pathlib import Path

        d = Path(out_dir)
        d.mkdir(parents=True, exist_ok=True)
        (d / "analysis.md").write_text("# Research: x\n\n## Summary\n\n.")
        return {
            "topic": topic,
            "out_dir": str(d),
            "variants_count": 1,
            "unique_urls_merged": 0,
            "pages_attempted": 0,
            "pages_written": 0,
            "failures": 0,
            "wall_seconds": 0.0,
        }

    monkeypatch.setattr(research_cli, "run_research", fake_run_research)
    called: list = []
    monkeypatch.setattr(
        research_cli, "_run_local_gate", lambda *a, **kw: called.append(a) or (True, [])
    )

    rc = research_cli.main(["x", f"--out={out_dir}", "--no-gates"])
    assert rc == 0
    assert called == [], "expected --no-gates to skip gate invocations"


def test_subcommand_dispatch_via_main(monkeypatch):
    """Verify the __main__ dispatch hands off to research_cli on argv[1]=='research'."""
    from supersearch import __main__ as ssmain

    captured: dict = {}

    def fake_research_main():
        captured["argv"] = list(sys.argv)
        return 0

    monkeypatch.setattr("supersearch.research_cli.main", fake_research_main)
    monkeypatch.setattr(sys, "argv", ["supersearch", "research", "--help"])
    with pytest.raises(SystemExit) as exc:
        ssmain.main()
    assert exc.value.code == 0
    assert captured["argv"][0] == "supersearch research"
    assert "--help" in captured["argv"]
