"""Verify built wheel and sdist behavior in fresh environments outside the checkout.

Only installation needs the network. Python/search probes deny socket access,
replace source adapters (not the orchestrator), and use -I and an empty working
tree. The separate direct console --version smoke runs without the socket guard.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tarfile
import tempfile
import venv
import zipfile


def clean_env(home: Path) -> dict[str, str]:
    return {"PATH": os.defpath, "HOME": str(home), "USERPROFILE": str(home),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""), "PYTHONDONTWRITEBYTECODE": "1"}


def run(command, cwd, env, expected=0):
    result = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, timeout=180)
    if result.returncode != expected:
        raise RuntimeError(f"command failed ({result.returncode}): {command}\n"
                           f"{result.stdout}\n{result.stderr}")
    return result


def source_resources(sdist: Path) -> dict[str, bytes]:
    """Read selected resources without extracting potentially unsafe tar paths."""
    with tarfile.open(sdist) as archive:
        members = archive.getmembers()
        roots = {member.name.split("/")[0] for member in members}
        assert len(roots) == 1, "sdist must have one root"
        root = roots.pop()
        files = {member.name[len(root) + 1:]: member for member in members if member.isfile()}

        def read(name):
            assert name in files, f"missing sdist resource: {name}"
            return archive.extractfile(files[name]).read()

        # Enforce the existing explicit packaging contract, including evaluation
        # receipts added by other changes, without maintaining a second file list.
        for line in read("MANIFEST.in").decode().splitlines():
            if line.startswith("include "):
                for name in line.split()[1:]:
                    if not any(char in name for char in "*?["):
                        read(name)
        public = set(read("scripts/public-files.txt").decode().splitlines())
        assert "scripts/check_installed.py" in public
        schema = read("docs/search-receipt-v1.schema.json")
        assert json.loads(schema)["properties"]["schema_version"]["const"] == "supersearch.search.v1"
        for name in ("plugin.json", "gemini-extension.json", "skills/supersearch/SKILL.md"):
            read(name)
        return {"schema.json": schema, "probe.py": read("scripts/check_installed.py")}


def probe(schema_path: Path, launcher: str | None = None, scenario="partial"):
    # Install the guard before importing the package or any HTTP dependencies.
    blocked = []

    def offline(event, args):
        if event in {"socket.connect", "socket.connect_ex", "socket.getaddrinfo", "socket.sendto"}:
            blocked.append(event)
            raise RuntimeError("installed probe network access denied")

    sys.addaudithook(offline)
    import socket

    try:
        socket.getaddrinfo("offline.invalid", 443)
    except RuntimeError:
        pass
    else:
        raise AssertionError("network guard did not block DNS")
    assert blocked == ["socket.getaddrinfo"]
    blocked.clear()

    import supersearch
    from supersearch import product, sources
    from supersearch.search import SearchResult
    from jsonschema import Draft202012Validator, FormatChecker

    origin = Path(supersearch.__file__).resolve()
    assert origin.is_relative_to(Path(sys.prefix).resolve()), "import escaped clean environment"
    assert "site-packages" in origin.parts, "checkout import leaked"
    assert not os.environ.get("PYTHONPATH")
    assert sys.flags.isolated and not sys.flags.optimize
    for name in ("DuckDuckGoSearch", "SearchResult", "fanout_search", "HackerNewsSearch",
                 "GitHubSearch", "ArxivSearch", "SemanticScholarSearch", "SearXNGSearch",
                 "search_all"):
        assert name in supersearch.__all__ and callable(getattr(supersearch, name)), name
    assert supersearch.fanout_search is product.search

    class Good:
        def search(self, query, max_results):
            assert query == "offline query" and max_results == 2
            print("controlled adapter stdout", file=sys.stdout)
            return [SearchResult("Offline page", "https://example.invalid/one", "Fixture")]

    class Failed:
        def search(self, query, max_results):
            raise RuntimeError("controlled source unavailable")

    # Keep production validation, fan-out, status propagation, provenance merging,
    # receipt serialization and CLI dispatch intact.
    adapters = {"good": Good, "failed": Failed}
    product._source_map = sources._source_map = lambda: adapters
    if launcher:
        selected = "good,failed" if scenario == "partial" else "failed"
        sys.argv = [launcher, "search", "offline query", "--sources", selected,
                    "--max-per-source", "2", "--deadline", "2"]
        if launcher == "module":
            runpy.run_module("supersearch", run_name="__main__")
        else:
            runpy.run_path(launcher, run_name="__main__")
        raise AssertionError("root CLI did not exit")

    from contextlib import redirect_stdout

    validator = Draft202012Validator(json.loads(schema_path.read_text()),
                                     format_checker=FormatChecker())
    receipts = {}
    for label, selected in (("partial", ["good", "failed"]), ("unavailable", ["failed"])):
        with redirect_stdout(sys.stderr):
            receipt = supersearch.fanout_search(" offline query ", sources=selected,
                                               max_per_source=2, deadline_seconds=2)
        check_receipt(receipt, label, validator)
        receipts[label] = receipt
    assert not blocked, "unexpected network attempt"
    print(json.dumps({"import_origin": str(origin), "python": sys.version,
                      "receipts": receipts, "network_attempts": blocked}))


def check_receipt(receipt, scenario, validator):
    validator.validate(receipt)
    assert receipt["query"] == "offline query"
    assert receipt["status"] == scenario, f"expected {scenario} receipt"
    assert receipt["execution"]["llm_required"] is False
    assert receipt["execution"]["deadline_enforced"] is True
    assert receipt["sources"][-1]["status"] == "failed"
    assert "controlled source unavailable" in receipt["sources"][-1]["diagnostics"][0]
    assert receipt["result_count"] == (1 if scenario == "partial" else 0)
    if scenario == "partial":
        assert receipt["sources"][0]["status"] == "completed"
        assert receipt["results"][0]["sources"] == ["good"]
        assert receipt["results"][0]["url"] == "https://example.invalid/one"
    else:
        assert receipt["results"] == []


def verify(wheel: Path, sdist: Path):
    from jsonschema import Draft202012Validator, FormatChecker

    resources = source_resources(sdist)
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        assert "supersearch/product.py" in names
        assert any(name.endswith(".dist-info/METADATA") for name in names)
        assert any(name.endswith(".dist-info/entry_points.txt") for name in names)
    report = {"artifacts": [], "limits": "Controlled adapters; no live source, model or quality claim."}
    for artifact in (wheel, sdist):
        with tempfile.TemporaryDirectory(prefix="supersearch-installed-") as temporary:
            root = Path(temporary).resolve()
            checkout = Path(__file__).resolve().parents[1]
            assert not root.is_relative_to(checkout), "temporary directory must be outside checkout"
            env = clean_env(root)
            working = root / "empty"
            working.mkdir()
            for name, content in resources.items():
                (root / name).write_bytes(content)
            environment = root / "venv"
            venv.EnvBuilder(with_pip=True, symlinks=os.name != "nt").create(environment)
            binaries = environment / ("Scripts" if os.name == "nt" else "bin")
            python = str(binaries / ("python.exe" if os.name == "nt" else "python"))
            console = str(binaries / "supersearch")
            run([python, "-I", "-m", "pip", "install", "--disable-pip-version-check",
                 str(artifact), "jsonschema>=4.23"], working, env)
            command = [python, "-I", "-B", str(root / "probe.py"), "--probe",
                       str(root / "schema.json")]
            observed = json.loads(run(command, working, env).stdout)
            validator = Draft202012Validator(json.loads(resources["schema.json"]),
                                             format_checker=FormatChecker())
            for launcher in (console, "module"):
                for scenario, status in (("partial", 0), ("unavailable", 3)):
                    result = run([*command, "--launcher", launcher, "--scenario", scenario],
                                 working, env, expected=status)
                    check_receipt(json.loads(result.stdout), scenario, validator)
                    assert "controlled source unavailable" in result.stderr
                    if scenario == "partial":
                        assert "controlled adapter stdout" in result.stderr
            # Execute the OS console script directly with network-free args;
            # this version smoke does not run inside the socket audit guard.
            if os.name != "nt":
                assert run([console, "--version"], working, env).stdout.strip()
            package = Path(observed["import_origin"]).parent
            product = package / "product.py"
            original = product.read_bytes()
            assert original.count(b'status = "partial"') == 1, "update behavioral control mutation"
            try:
                product.write_bytes(original.replace(b'status = "partial"', b'status = "ok"'))
                broken = subprocess.run(command, cwd=working, env=env, capture_output=True,
                                        text=True, timeout=30)
                assert broken.returncode != 0 and "expected partial receipt" in broken.stderr
            finally:
                product.write_bytes(original)
            missing = package / "product.missing"
            product.rename(missing)
            try:
                broken = subprocess.run(command, cwd=working, env=env, capture_output=True,
                                        text=True, timeout=30)
                assert broken.returncode != 0 and "supersearch.product" in broken.stderr
            finally:
                missing.rename(product)
            # Restoration proves the controls did not merely poison the environment.
            run(command, working, env)
            report["artifacts"].append({"name": artifact.name,
                "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(), **observed,
                "controls": ["wrong partial status rejected", "missing installed module rejected",
                             "restored package passes"],
                "assertions": ["isolated site-packages import", "public Python exports",
                               "schema-valid partial/unavailable Python receipts",
                               "console/module CLI JSON and exits 0/3", "stderr isolation",
                               "sdist explicit resources", "Python/search network guard",
                               "direct console version smoke (unguarded)"]})
    return report


def main():
    if sys.flags.optimize:
        raise SystemExit("installed checks require assertions; do not run Python with -O")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", nargs="*", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--probe", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--launcher", help=argparse.SUPPRESS)
    parser.add_argument("--scenario", default="partial", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.probe:
        probe(args.probe, args.launcher, args.scenario)
        return
    wheels = [path.resolve() for path in args.artifacts if path.suffix == ".whl"]
    sdists = [path.resolve() for path in args.artifacts if path.name.endswith(".tar.gz")]
    if len(wheels) != 1 or len(sdists) != 1 or len(args.artifacts) != 2:
        parser.error("provide exactly one wheel and one .tar.gz sdist")
    result = verify(wheels[0], sdists[0])
    payload = json.dumps(result, indent=2) + "\n"
    if args.report:
        args.report.write_text(payload)
    print(payload, end="")


if __name__ == "__main__":
    main()
