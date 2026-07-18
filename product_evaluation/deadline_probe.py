"""Process-level control for the Product V1 CLI deadline.

The child registers a deliberately slow atexit hook inside a timed-out source.
The Product V1 command must flush a partial receipt and close without waiting
for that third-party cleanup hook.
"""

from __future__ import annotations

import argparse
import atexit
import json
from pathlib import Path
import subprocess
import sys
import time


def _child() -> None:
    from supersearch import product, sources
    from supersearch.search import SearchResult

    class Fast:
        def search(self, query: str, max_results: int = 3):
            return [
                SearchResult(
                    title="fast result",
                    url="https://example.test/fast",
                    snippet="fixture",
                )
            ]

    class SlowWithCleanup:
        def search(self, query: str, max_results: int = 3):
            atexit.register(time.sleep, 30)
            time.sleep(30)
            return []

    source_map = lambda: {"fast": Fast, "slow": SlowWithCleanup}  # noqa: E731
    sources._source_map = source_map
    product._source_map = source_map
    sys.argv = [
        "supersearch",
        "search",
        "deadline control",
        "--sources",
        "fast,slow",
        "--deadline",
        "0.25",
    ]
    from supersearch.__main__ import main

    main()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--child", action="store_true")
    args = parser.parse_args()
    if args.child:
        _child()
        return 0

    started = time.monotonic()
    completed = subprocess.run(
        [
            str(args.python),
            str(Path(__file__).resolve()),
            "--python",
            str(args.python),
            "--output",
            str(args.output),
            "--child",
        ],
        capture_output=True,
        text=True,
        timeout=3,
    )
    wall_ms = round((time.monotonic() - started) * 1000, 3)
    receipt = json.loads(completed.stdout)
    summary = {
        "schema_version": "supersearch.deadline-process-control.v1",
        "return_code": completed.returncode,
        "wall_ms": wall_ms,
        "deadline_seconds": receipt["execution"]["deadline_seconds"],
        "receipt_duration_ms": receipt["execution"]["duration_ms"],
        "receipt_status": receipt["status"],
        "source_states": {
            source["name"]: source["status"] for source in receipt["sources"]
        },
        "result_count": receipt["result_count"],
        "passed": (
            completed.returncode == 0
            and wall_ms < 1500
            and receipt["status"] == "partial"
            and receipt["result_count"] == 1
            and receipt["sources"][1]["status"] == "timed_out"
        ),
        "control": "timed-out source registered a 30-second atexit hook; CLI must not wait for it after flushing the receipt",
        "stderr": completed.stderr,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    if not summary["passed"]:
        print(json.dumps(summary, indent=2), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
