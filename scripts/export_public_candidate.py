"""Export reviewed public files from a clean, exact Git HEAD."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "scripts/public-files.txt"
FORBIDDEN_PATTERNS = (
    ("absolute home path", re.compile(r"/(?:" + "Users|home" + r")/[A-Za-z0-9._-]+")),
    ("Windows home path", re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+[A-Za-z0-9._-]+")),
    (
        "home-relative workspace path",
        re.compile(r"~/" + r"(?:ai-infra|Documents|dev|projects)(?:/|\b)"),
    ),
    ("local workspace path", re.compile(r"(?:\.control|_workspace)/[A-Za-z0-9._-]+")),
)


def _privacy_violation(text: str) -> str | None:
    """Return a generic label without reproducing potentially private content."""
    return next(
        (label for label, pattern in FORBIDDEN_PATTERNS if pattern.search(text)),
        None,
    )


def _git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=REPO_ROOT)


def _public_files(content: str) -> list[str]:
    paths = [line.strip() for line in content.splitlines() if line.strip() and not line.startswith("#")]
    if len(paths) != len(set(paths)):
        raise SystemExit("duplicate public file entry")
    for path in paths:
        parts = PurePosixPath(path).parts
        if (
            not parts or path.startswith("/") or ".." in parts
            or str(PurePosixPath(path)) != path
            or any(char in path for char in "\\:*?[]\x00")
        ):
            raise SystemExit("invalid public file entry")
    if MANIFEST not in paths:
        raise SystemExit("public file list must include itself")
    return sorted(paths)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--destination", type=Path)
    mode.add_argument("--check", action="store_true", help="also reject unlisted tracked files")
    args = parser.parse_args()
    if args.destination is not None and args.destination.exists():
        raise SystemExit("destination already exists")
    if _git("status", "--porcelain").strip():
        raise SystemExit("public export requires a clean exact Git boundary")

    head = _git("rev-parse", "HEAD").decode().strip()
    selected = _public_files(_git("show", f"{head}:{MANIFEST}").decode("utf-8"))
    entries = {}
    for entry in _git("ls-tree", "-rz", head).split(b"\x00"):
        if entry:
            meta, path = entry.split(b"\t", 1)
            file_mode, kind, oid = meta.decode().split()
            entries[path.decode("utf-8")] = (file_mode, kind, oid)
    if args.check and set(entries) - set(selected):
        raise SystemExit("tracked files outside public file list; review before export")

    # Preflight everything before creating an export, so failure leaves no partial tree.
    contents: dict[str, bytes] = {}
    hashes: dict[str, str] = {}
    for relative in selected:
        entry = entries.get(relative)
        if entry is None:
            raise SystemExit(f"public file is not committed: {relative}")
        file_mode, kind, oid = entry
        if kind != "blob" or file_mode not in {"100644", "100755"}:
            raise SystemExit(f"public file must be a regular file: {relative}")
        content = _git("cat-file", "blob", oid)
        try:
            decoded = content.decode("utf-8")
        except UnicodeDecodeError:
            raise SystemExit(f"public file requires a binary content review: {relative}") from None
        if "\x00" in decoded:
            raise SystemExit(f"public file requires a binary content review: {relative}")
        violation = _privacy_violation(decoded)
        if violation is not None:
            raise SystemExit(f"privacy check failed for {relative}: {violation}")
        contents[relative] = content
        hashes[relative] = hashlib.sha256(content).hexdigest()

    aggregate = hashlib.sha256()
    for relative, digest in hashes.items():
        aggregate.update(f"{relative}\x00{digest}\n".encode())
    receipt = {
        "schema_version": "supersearch.public-export.v1",
        "source_git_head": head,
        "file_count": len(hashes),
        "aggregate_sha256": aggregate.hexdigest(),
        "files": hashes,
        "excluded_internal_surfaces": ["files outside the reviewed public file list"],
    }
    if args.destination is not None:
        args.destination.mkdir(parents=True)
        for relative, content in contents.items():
            target = args.destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            if entries[relative][0] == "100755":
                target.chmod(0o755)
        (args.destination / "PUBLIC-EXPORT-RECEIPT.json").write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n"
        )
    print(json.dumps({key: receipt[key] for key in ("source_git_head", "file_count", "aggregate_sha256")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
