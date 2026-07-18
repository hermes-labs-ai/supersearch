"""CLI entry point for `supersearch verify`."""

from __future__ import annotations

import argparse
import sys

from supersearch import __version__


def _bounded_sources(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer from 1 to 20") from exc
    if not 1 <= number <= 20:
        raise argparse.ArgumentTypeError("must be from 1 to 20")
    return number


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="supersearch verify",
        description="Evaluate a claim against retrieved evidence. Returns SUPPORTED | "
        "CONTRADICTED | UNVERIFIED | CONFLICTING with URLs, explicit evidence "
        "provenance, availability status, freshness, and numeric-conflict signals.",
    )
    p.add_argument("claim", nargs="?", help="The claim to verify (quoted).")
    p.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    p.add_argument(
        "--max-sources",
        type=_bounded_sources,
        default=12,
        help="Maximum evidence sources (1-20; default: 12).",
    )
    p.add_argument(
        "--no-gates",
        action="store_true",
        help="Skip the package-owned offline receipt-integrity gate.",
    )
    p.add_argument(
        "--deep",
        action="store_true",
        help="Fetch top pages and label fetched-page versus snippet fallback evidence explicitly.",
    )
    p.add_argument(
        "--version", action="version", version=f"supersearch verify {__version__}"
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.claim:
        parser.print_help(sys.stderr)
        return 2

    from .formatter import format_json, format_markdown
    from .pipeline import verify_claim

    result = verify_claim(args.claim, max_sources=args.max_sources, deep=args.deep)
    output = format_json(result) if args.json else format_markdown(result)
    sys.stdout.write(output)
    sys.stdout.write("\n" if not output.endswith("\n") else "")

    if not args.no_gates:
        from .gates import run_reality_gates

        gate = run_reality_gates(result)
        if not gate.ok:
            print("supersearch verify: receipt integrity gate FAILED", file=sys.stderr)
            for check in gate.checks:
                if not check.ok:
                    print(f"  {check.name}: {check.detail}", file=sys.stderr)
            return 3

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
