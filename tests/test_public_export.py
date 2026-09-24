"""Exercise the export boundary against committed fixture repositories."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import export_public_candidate as exporter


def _git(repo, *args):
    return subprocess.check_output(
        ["git", "-c", "core.hooksPath=/dev/null", "-C", str(repo), *args],
        stderr=subprocess.STDOUT,
    )


def _commit(repo):
    _git(repo, "add", ".")
    _git(repo, "-c", "user.name=Export Test", "-c", "user.email=test@example.invalid",
         "commit", "-m", "fixture")


@pytest.fixture
def source(tmp_path, monkeypatch):
    repo = tmp_path / "source"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "scripts").mkdir()
    (repo / "docs").mkdir()
    (repo / exporter.MANIFEST).write_text(exporter.MANIFEST + "\ndocs/public.md\n")
    (repo / "docs/public.md").write_text("Public product documentation.\n")
    _commit(repo)
    monkeypatch.setattr(exporter, "REPO_ROOT", repo)
    return repo


def _run(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["export_public_candidate.py", *map(str, args)])
    return exporter.main()


def test_exact_list_excludes_new_files_even_in_public_directories(source, tmp_path, monkeypatch):
    (source / "docs/operator-notes.md").write_text("Not reviewed for export.\n")
    (source / "scripts/session.py").write_text("# Not reviewed for export.\n")
    (source / "docs/public.md").chmod(0o755)
    _commit(source)
    destination = tmp_path / "export"
    assert _run(monkeypatch, "--destination", destination) == 0
    assert not (destination / "docs/operator-notes.md").exists()
    assert not (destination / "scripts/session.py").exists()
    assert (destination / "docs/public.md").stat().st_mode & 0o111
    receipt = json.loads((destination / "PUBLIC-EXPORT-RECEIPT.json").read_text())
    assert receipt["source_git_head"] == _git(source, "rev-parse", "HEAD").decode().strip()
    for name, digest in receipt["files"].items():
        assert hashlib.sha256((destination / name).read_bytes()).hexdigest() == digest
    with pytest.raises(SystemExit, match="outside public file list"):
        _run(monkeypatch, "--check")


@pytest.mark.parametrize("bad_content", [
    "/" + "Users/example/workspace/file",
    "/" + "home/example/workspace/file",
    "C:" + "\\Users\\example\\workspace\\file",
    "~/" + "ai-infra/tool",
    "." + "control/session.log",
])
def test_private_path_rejected_without_partial_export(source, tmp_path, monkeypatch, bad_content):
    (source / "docs/public.md").write_text(bad_content)
    _commit(source)
    destination = tmp_path / "export"
    with pytest.raises(SystemExit, match="privacy check failed") as error:
        _run(monkeypatch, "--destination", destination)
    assert bad_content not in str(error.value)
    assert not destination.exists()


def test_symlink_rejected(source, tmp_path, monkeypatch):
    (source / "docs/link.md").symlink_to("public.md")
    with (source / exporter.MANIFEST).open("a") as stream:
        stream.write("docs/link.md\n")
    _commit(source)
    destination = tmp_path / "export"
    with pytest.raises(SystemExit, match="regular file"):
        _run(monkeypatch, "--destination", destination)
    assert not destination.exists()


def test_dirty_or_incomplete_boundary_rejected(source, tmp_path, monkeypatch):
    (source / "docs/public.md").write_text("uncommitted change")
    with pytest.raises(SystemExit, match="clean exact Git boundary"):
        _run(monkeypatch, "--check")
    _commit(source)
    with (source / exporter.MANIFEST).open("a") as stream:
        stream.write("missing.md\n")
    _commit(source)
    with pytest.raises(SystemExit, match="not committed"):
        _run(monkeypatch, "--destination", tmp_path / "export")
    assert not (tmp_path / "export").exists()


def test_public_receipt_hashes_match_current_files():
    root = Path(__file__).parents[1]
    results = root / "product_evaluation/results"
    proof = json.loads((results / "PRODUCT-RECEIPT.json").read_text())["proof"]
    for key, path in {
        "preregistration_sha256": root / "product_evaluation/PREREGISTRATION.json",
        "public_live_summary_sha256": results / "PUBLIC-LIVE-SUMMARY.json",
        "human_evaluation_sha256": results / "HUMAN-EVALUATION.json",
        "host_trials_sha256": results / "HOST-TRIALS.json",
    }.items():
        assert proof[key] == hashlib.sha256(path.read_bytes()).hexdigest(), key
    assert proof["deadline_control"]["sha256"] == hashlib.sha256(
        (results / "DEADLINE-CONTROL.json").read_bytes()
    ).hexdigest()
