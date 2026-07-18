"""Run the preregistered Product V1 pack through Codex and Claude/Fable."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shlex
import subprocess
import time

from jsonschema import Draft202012Validator


def _prompt(host: str, executable: Path, cache_dir: Path, prereg: dict) -> str:
    commands = []
    unset = (
        "env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY -u GITHUB_TOKEN "
        "-u TAVILY_API_KEY -u EXA_API_KEY -u FIRECRAWL_API_KEY"
    )
    config = prereg["configuration"]
    quoted_executable = shlex.quote(str(executable))
    quoted_cache_dir = shlex.quote(str(cache_dir))
    quoted_sources = shlex.quote(",".join(config["sources"]))
    for query in prereg["queries"]:
        commands.append(
            f"{query['id']}: {unset} SUPERSEARCH_CACHE_DIR={quoted_cache_dir} "
            f"{quoted_executable} search {shlex.quote(query['query'])} "
            f"--sources {quoted_sources} "
            f"--max-per-source {config['max_per_source']} "
            f"--deadline {config['deadline_seconds']}"
        )
    criteria = "\n".join(
        f"- {item['id']}: useful iff {item['useful_if']}"
        for item in prereg["queries"]
    )
    return f"""You are the {host} host in a bounded SuperSearch interoperability trial.

Run exactly the three shell commands below. Do not edit files, install anything,
use another web/search tool, rewrite the queries, or call a model from inside
SuperSearch. Each command points to the same clean wheel installation and
removes paid/search/model key environment variables from the SuperSearch
subprocess. Parse its one JSON stdout document.

{chr(10).join(commands)}

Select at most one useful result per query under these fixed criteria:
{criteria}

Return only the JSON object required by the supplied output schema. Set host to
{json.dumps(host)}. Preserve receipt status, result_count, and every source
state exactly. `useful_result` may be null. A URL/snippet is source discovery,
not a factual answer or certification; say that in `nonclaim`. Set
`bespoke_adapter_needed` based only on whether you could execute and parse the
CLI/JSON contract.
"""


def _run(
    command: list[str], timeout: int = 240
) -> tuple[subprocess.CompletedProcess, float]:
    started = time.monotonic()
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return completed, round((time.monotonic() - started) * 1000, 3)


def _worktree_status(repo: Path) -> str:
    """Return the non-ignored Git status used to detect host-side mutation."""

    return subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=repo, text=True
    )


def _validate_host_stdout(
    host: str, stdout: str, schema: dict
) -> tuple[bool, str | None]:
    """Validate the host's actual stdout, including Claude's JSON envelope."""

    try:
        outer = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return False, f"stdout is not JSON at line {exc.lineno}, column {exc.colno}"

    document = outer
    if host == "claude-fable":
        if isinstance(outer, dict) and isinstance(
            outer.get("structured_output"), dict
        ):
            document = outer["structured_output"]
        elif isinstance(outer, dict) and isinstance(outer.get("result"), str):
            try:
                document = json.loads(outer["result"])
            except json.JSONDecodeError as exc:
                return (
                    False,
                    "Claude result is not JSON at "
                    f"line {exc.lineno}, column {exc.colno}",
                )
        else:
            return False, "Claude envelope has no structured_output or JSON result"

    errors = sorted(
        Draft202012Validator(schema).iter_errors(document),
        key=lambda error: [str(part) for part in error.absolute_path],
    )
    if errors:
        error = errors[0]
        path = "$" + "".join(f"[{part!r}]" for part in error.absolute_path)
        return False, f"schema validation failed at {path}: {error.message}"

    if document["host"] != host:
        return False, f"host identity mismatch: expected {host!r}"
    query_ids = [query["id"] for query in document["queries"]]
    if query_ids != ["Q1", "Q2", "Q3"]:
        return False, "query ids must be exactly Q1, Q2, Q3 in preregistered order"
    return True, None


def _host_summary(
    host: str,
    completed: subprocess.CompletedProcess,
    wall_ms: float,
    schema: dict,
) -> dict:
    output_valid, validation_error = _validate_host_stdout(
        host, completed.stdout, schema
    )
    return {
        "host": host,
        "return_code": completed.returncode,
        "wall_ms": wall_ms,
        "output_valid": output_valid,
        "validation_error": validation_error,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--codex", type=Path, required=True)
    parser.add_argument("--claude", type=Path, required=True)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument(
        "--only", choices=("all", "codex", "claude"), default="all"
    )
    parser.add_argument(
        "--codex-sandbox",
        choices=("read-only", "workspace-write", "danger-full-access"),
        default="read-only",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    repo = root.parent
    initial_worktree_status = _worktree_status(repo)
    prereg = json.loads((root / "PREREGISTRATION.json").read_text())
    schema_path = root / "host-trial-output.schema.json"
    schema = json.loads(schema_path.read_text())
    args.output_dir.mkdir(parents=True, exist_ok=False)
    args.cache_root.mkdir(parents=True, exist_ok=True)

    hosts = []
    if args.only in {"all", "codex"}:
        codex_prompt = _prompt(
            "codex",
            args.executable.resolve(),
            (args.cache_root / "codex").resolve(),
            prereg,
        )
        codex, codex_ms = _run(
            [
                str(args.codex),
                "exec",
                "--ephemeral",
                "--sandbox",
                args.codex_sandbox,
                "--model",
                "gpt-5.4-mini",
                "--cd",
                str(repo),
                "--output-schema",
                str(schema_path),
                "--color",
                "never",
                codex_prompt,
            ]
        )
        (args.output_dir / "codex.stdout.txt").write_text(codex.stdout)
        (args.output_dir / "codex.stderr.txt").write_text(codex.stderr)
        hosts.append(_host_summary("codex", codex, codex_ms, schema))

    if args.only in {"all", "claude"}:
        claude_prompt = _prompt(
            "claude-fable",
            args.executable.resolve(),
            (args.cache_root / "claude-fable").resolve(),
            prereg,
        )
        claude_schema = {
            key: value for key, value in schema.items() if key != "$schema"
        }
        claude, claude_ms = _run(
            [
                str(args.claude),
                "--print",
                "--model",
                "fable",
                "--safe-mode",
                "--no-session-persistence",
                "--permission-mode",
                "dontAsk",
                "--allowedTools=Bash",
                "--output-format",
                "json",
                "--json-schema",
                json.dumps(claude_schema, separators=(",", ":")),
                claude_prompt,
            ]
        )
        (args.output_dir / "claude-fable.stdout.txt").write_text(claude.stdout)
        (args.output_dir / "claude-fable.stderr.txt").write_text(claude.stderr)
        hosts.append(
            _host_summary("claude-fable", claude, claude_ms, schema)
        )

    worktree_unchanged = _worktree_status(repo) == initial_worktree_status
    summary = {
        "schema_version": "supersearch.host-trial-run.v1",
        "run_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "clean_install_executable": str(args.executable.resolve()),
        "hosts": hosts,
        "worktree_unchanged": worktree_unchanged,
        "note": "raw stdout/stderr are retained; host conclusions are integration-friction evidence, not truth evidence",
    }
    (args.output_dir / "RUN-SUMMARY.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    return (
        0
        if all(
            host["return_code"] == 0 and host["output_valid"] for host in hosts
        )
        and worktree_unchanged
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
