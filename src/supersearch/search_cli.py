"""Agent-safe CLI for the Product V1 search receipt."""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import json
import sys

from . import __version__
from .product import DEFAULT_SOURCES, available_sources, search


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="supersearch search",
        description=(
            "Fan one query out to public search surfaces under one deadline and "
            "write one versioned JSON receipt to stdout."
        ),
    )
    parser.add_argument("query", nargs="?", help="query text")
    parser.add_argument(
        "--sources",
        default=",".join(DEFAULT_SOURCES),
        help="comma-separated source names (default: %(default)s)",
    )
    parser.add_argument(
        "--max-per-source", type=int, default=3, help="result cap per source"
    )
    parser.add_argument(
        "--deadline", type=float, default=15.0, help="total wall-clock deadline"
    )
    parser.add_argument("--serial", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--pretty", action="store_true", help="indent JSON for human reading"
    )
    parser.add_argument(
        "--list-sources", action="store_true", help="print registered sources as JSON"
    )
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.list_sources:
        print(json.dumps({"sources": available_sources()}, sort_keys=True))
        return 0
    if not args.query:
        build_parser().error("query is required unless --list-sources is used")

    source_names = [item.strip() for item in args.sources.split(",") if item.strip()]
    receipt_stream = sys.stdout
    with redirect_stdout(sys.stderr):
        try:
            receipt = search(
                args.query,
                sources=source_names,
                max_per_source=args.max_per_source,
                deadline_seconds=args.deadline,
                parallel=not args.serial,
                rerank=False,
            )
        except ValueError as exc:
            print(f"supersearch search: {exc}", file=sys.stderr)
            return 2

        if args.pretty:
            payload = json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False)
        else:
            payload = json.dumps(
                receipt,
                separators=(",", ":"),
                sort_keys=True,
                allow_nan=False,
            )
        # Source/library writes remain redirected until the agent receipt has
        # reached the original stdout stream. The root CLI then flushes and
        # hard-exits, so timed-out daemon adapters cannot append late output.
        receipt_stream.write(payload + "\n")
        receipt_stream.flush()
    return 3 if receipt["status"] == "unavailable" else 0


if __name__ == "__main__":
    raise SystemExit(main())
