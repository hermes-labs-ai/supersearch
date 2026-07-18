"""Run the preregistered Product V1 live query pack from an installed CLI.

The script records receipts and descriptive measurements. It deliberately does
not score relevance or truth; human usefulness labels are applied separately
under the preregistered criteria.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.parse import urlparse

KEY_ENVIRONMENT_NAMES = (
    "ANTHROPIC_API_KEY",
    "EXA_API_KEY",
    "FIRECRAWL_API_KEY",
    "GITHUB_TOKEN",
    "OPENAI_API_KEY",
    "TAVILY_API_KEY",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(command: list[str], env: dict[str, str], timeout: float) -> tuple:
    started = time.monotonic()
    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        timeout=timeout,
        env=env,
    )
    wall_ms = round((time.monotonic() - started) * 1000, 3)
    return completed, wall_ms


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    prereg_path = root / "PREREGISTRATION.json"
    prereg = json.loads(prereg_path.read_text())
    args.output_dir.mkdir(parents=True, exist_ok=False)
    args.cache_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    for name in KEY_ENVIRONMENT_NAMES:
        env.pop(name, None)
    env["SUPERSEARCH_CACHE_DIR"] = str(args.cache_dir.resolve())

    version_run, _ = _run(
        [str(args.executable), "search", "--version"], env, timeout=10
    )
    if version_run.returncode != 0:
        raise RuntimeError(version_run.stderr)

    config = prereg["configuration"]
    sources_arg = ",".join(config["sources"])
    rows = []
    # Alternate call order to avoid always favoring one mode with a warm DDGS
    # cache. This still remains descriptive because the public network changes.
    order_by_query = {
        "Q1": ("serial", "parallel"),
        "Q2": ("parallel", "serial"),
        "Q3": ("serial", "parallel"),
    }

    for query_item in prereg["queries"]:
        query_id = query_item["id"]
        for mode in order_by_query[query_id]:
            command = [
                str(args.executable),
                "search",
                query_item["query"],
                "--sources",
                sources_arg,
                "--max-per-source",
                str(config["max_per_source"]),
                "--deadline",
                str(config["deadline_seconds"]),
            ]
            if mode == "serial":
                command.append("--serial")
            completed, wall_ms = _run(
                command, env, timeout=float(config["deadline_seconds"]) * 5 + 10
            )
            try:
                receipt = json.loads(completed.stdout)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"{query_id}/{mode} emitted invalid JSON: {completed.stdout!r}"
                ) from exc
            receipt_path = args.output_dir / f"{query_id}.{mode}.json"
            receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
            stderr_path = args.output_dir / f"{query_id}.{mode}.stderr.txt"
            stderr_path.write_text(completed.stderr)

            domains = sorted(
                {
                    (urlparse(result["url"]).hostname or "").lower()
                    for result in receipt["results"]
                    if result.get("url")
                }
                - {""}
            )
            represented_sources = sorted(
                {
                    source
                    for result in receipt["results"]
                    for source in result.get("sources", [])
                }
            )
            rows.append(
                {
                    "query_id": query_id,
                    "mode": mode,
                    "call_order": order_by_query[query_id].index(mode) + 1,
                    "return_code": completed.returncode,
                    "receipt_status": receipt["status"],
                    "wall_ms": wall_ms,
                    "receipt_duration_ms": receipt["execution"]["duration_ms"],
                    "result_count": receipt["result_count"],
                    "unique_domain_count": len(domains),
                    "unique_domains": domains,
                    "represented_sources": represented_sources,
                    "source_states": {
                        source["name"]: source["status"]
                        for source in receipt["sources"]
                    },
                    "receipt": receipt_path.name,
                    "stderr": stderr_path.name,
                    "receipt_sha256": _sha256(receipt_path),
                }
            )

    summary = {
        "schema_version": "supersearch.product-live-pack.v1",
        "run_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "scope": "three preregistered queries on one machine/network; descriptive, not general",
        "preregistration_sha256": _sha256(prereg_path),
        "wheel": {
            "filename": args.wheel.name,
            "sha256": _sha256(args.wheel),
            "reported_version": version_run.stdout.strip(),
        },
        "environment": {
            "supersearch_cache_dir": str(args.cache_dir.resolve()),
            "removed_credential_environment_names": list(KEY_ENVIRONMENT_NAMES),
            "llm_requested_by_cli": False,
        },
        "configuration": config,
        "rows": rows,
        "limitations": [
            "public indexes and network conditions can change between calls",
            "DDGS cache state can favor the second mode for a query",
            "serial mode is a comparison control and does not enforce the total deadline",
            "counts do not measure factual truth or general search quality",
        ],
    }
    summary_path = args.output_dir / "MACHINE-SUMMARY.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
