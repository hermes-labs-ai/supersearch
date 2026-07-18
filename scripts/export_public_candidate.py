"""Create a privacy-checked public source export from the exact Git HEAD.

The internal Evidence Bridge component and raw host logs remain in the sealed
working candidate but are not part of the standalone public product surface.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

REPO_ROOT = Path(__file__).resolve().parents[1]

ROOT_FILES = {
    ".gitattributes",
    ".gitignore",
    "CITATION.cff",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "MANIFEST.in",
    "README.md",
    "SECURITY.md",
    "llms.txt",
    "pyproject.toml",
}
PUBLIC_PREFIXES = (".github/", "docs/", "examples/", "scripts/", "src/", "tests/")
PRODUCT_EVALUATION_FILES = {
    "product_evaluation/FIVE-MINUTE-SHOWCASE.md",
    "product_evaluation/PREREGISTRATION.json",
    "product_evaluation/PREREGISTRATION.md",
    "product_evaluation/PRODUCT-DECISION.md",
    "product_evaluation/README.md",
    "product_evaluation/deadline_probe.py",
    "product_evaluation/host-trial-output.schema.json",
    "product_evaluation/run_host_trials.py",
    "product_evaluation/run_live_pack.py",
    "product_evaluation/results/BENCHMARK.md",
    "product_evaluation/results/CLEAN-INSTALL.json",
    "product_evaluation/results/DEADLINE-CONTROL.json",
    "product_evaluation/results/HOST-TRIALS.json",
    "product_evaluation/results/HOST-TRIALS.md",
    "product_evaluation/results/HUMAN-EVALUATION.json",
    "product_evaluation/results/HUMAN-EVALUATION.md",
    "product_evaluation/results/PRODUCT-RECEIPT.json",
    "product_evaluation/results/PUBLIC-LIVE-SUMMARY.json",
}
FORBIDDEN_PATTERNS = (
    (
        "absolute macOS home path",
        re.compile("/" + "Users" + r"/[A-Za-z0-9._-]+"),
    ),
    (
        "absolute Linux home path",
        re.compile("/" + "home" + r"/[A-Za-z0-9._-]+"),
    ),
    (
        "home-relative internal tool path",
        re.compile("~" + r"/ai-infra(?:/|$)"),
    ),
    ("internal HAL workspace path", re.compile("HAL/" + "_workspace")),
)


def _privacy_violation(text: str) -> str | None:
    """Return a generic violation label without embedding local identity data."""

    return next(
        (label for label, pattern in FORBIDDEN_PATTERNS if pattern.search(text)),
        None,
    )


def _git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=REPO_ROOT)


def _selected(path: str) -> bool:
    if path in ROOT_FILES or path in PRODUCT_EVALUATION_FILES:
        return True
    if path.startswith("product_evaluation/results/live-final/Q"):
        return path.endswith((".json", ".stderr.txt"))
    return path.startswith(PUBLIC_PREFIXES)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    if args.destination.exists():
        raise SystemExit(f"destination already exists: {args.destination}")
    if _git("status", "--porcelain").strip():
        raise SystemExit("public export requires a clean exact Git boundary")

    head = _git("rev-parse", "HEAD").decode().strip()
    tracked = _git("ls-files").decode().splitlines()
    selected = sorted(path for path in tracked if _selected(path))
    if "product_evaluation/results/PRODUCT-RECEIPT.json" not in selected:
        raise SystemExit("final product receipt is not committed")

    args.destination.mkdir(parents=True)
    hashes: dict[str, str] = {}
    for relative in selected:
        content = _git("show", f"{head}:{relative}")
        if b"\x00" not in content:
            text = content.decode("utf-8")
            violation = _privacy_violation(text)
            if violation is not None:
                raise SystemExit(
                    f"privacy check failed for {relative}: {violation}"
                )
        target = args.destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        mode = _git("ls-files", "-s", "--", relative).decode().split()[0]
        if mode == "100755":
            target.chmod(0o755)
        hashes[relative] = hashlib.sha256(content).hexdigest()

    aggregate = hashlib.sha256()
    for relative, digest in hashes.items():
        aggregate.update(relative.encode())
        aggregate.update(b"\x00")
        aggregate.update(digest.encode())
        aggregate.update(b"\n")
    receipt = {
        "schema_version": "supersearch.public-export.v1",
        "source_git_head": head,
        "file_count": len(hashes),
        "aggregate_sha256": aggregate.hexdigest(),
        "files": hashes,
        "excluded_internal_surfaces": [
            "evidence_showcase/",
            "raw Codex and Claude host logs",
            "pre-repair live evaluation receipts",
            "local control/build environments",
        ],
    }
    (args.destination / "PUBLIC-EXPORT-RECEIPT.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps({key: receipt[key] for key in ("source_git_head", "file_count", "aggregate_sha256")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
