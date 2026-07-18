"""CLI entry point for ``supersearch research`` with offline local gates."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from . import __version__ as _pkg_version
from .research import run_research

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_REQUIRED_SECTIONS = (
    "## Summary",
    "## Top Entities",
    "## Freshness",
    "## Contradictions",
    "## Variants used",
    "## Sources",
)


def _slug(topic: str, max_len: int = 64) -> str:
    s = _SLUG_RE.sub("-", topic.lower()).strip("-")
    return (s or "research")[:max_len]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="supersearch research",
        description="Multi-hop research: expand → search → entity fan-out → "
        "fetch → summarize → write a structured corpus.",
    )
    p.add_argument("topic", help="Topic to research (quoted).")
    p.add_argument(
        "--depth",
        type=int,
        default=1,
        help="Multi-hop depth (0 disables entity fan-out).",
    )
    p.add_argument("--max-pages", type=int, default=50, help="Max pages to fetch.")
    p.add_argument(
        "--out",
        default=None,
        help="Output directory (default: /tmp/supersearch-research/<slug>).",
    )
    p.add_argument(
        "--no-gates",
        action="store_true",
        help="Skip package-owned offline corpus-structure checks.",
    )
    p.add_argument(
        "--max-workers-fetch",
        type=int,
        default=10,
        help="ThreadPool size for parallel page fetches (capped at 10 per spec).",
    )
    p.add_argument(
        "--fetch-timeout",
        type=int,
        default=15,
        help="Per-page fetch timeout in seconds.",
    )
    p.add_argument(
        "--version", action="version", version=f"supersearch research {_pkg_version}"
    )
    return p


def _run_local_gate(target: Path) -> tuple[bool, list[str]]:
    """Validate the generated analysis shape without scripts or network."""
    if not target.is_file():
        return False, ["analysis.md not produced"]
    try:
        body = target.read_text(encoding="utf-8")
    except OSError as exc:
        return False, [f"analysis.md unreadable: {exc}"]
    positions = [body.find(section) for section in _REQUIRED_SECTIONS]
    errors = [
        f"missing section: {section}"
        for section, position in zip(_REQUIRED_SECTIONS, positions, strict=True)
        if position < 0
    ]
    present = [position for position in positions if position >= 0]
    if present != sorted(present):
        errors.append("required sections are out of order")
    return not errors, errors


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.topic or not args.topic.strip():
        parser.print_help(sys.stderr)
        return 2

    out_dir = args.out or f"/tmp/supersearch-research/{_slug(args.topic)}"
    workers = max(1, min(10, args.max_workers_fetch))

    stats = run_research(
        args.topic,
        depth=args.depth,
        max_pages=args.max_pages,
        out_dir=out_dir,
        max_workers_fetch=workers,
        fetch_timeout=args.fetch_timeout,
    )

    print(f"\n📁 Wrote corpus to: {stats['out_dir']}")
    print(
        f"   variants={stats['variants_count']}  unique_urls={stats['unique_urls_merged']}"
        f"  pages={stats['pages_written']}/{stats['pages_attempted']}  "
        f"failures={stats['failures']}  wall={stats['wall_seconds']:.1f}s"
    )

    if args.no_gates:
        return 0

    ok, errors = _run_local_gate(Path(out_dir) / "analysis.md")
    if not ok:
        for error in errors:
            print(f"GATE FAILED: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
