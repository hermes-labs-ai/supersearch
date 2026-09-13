"""Offline checks for the portable Agent Plugin surface at the repository root.

The root is one Agent Plugin (`plugin.json` + `skills/supersearch/SKILL.md`).
Claude Code, Codex CLI, and Gemini CLI manifests must all resolve that same
root so there is exactly one SKILL.md, and every identity field and runner pin
must track pyproject.toml instead of drifting.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "supersearch" / "SKILL.md"
PYPROJECT = ROOT / "pyproject.toml"


def _load(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def _pyproject(name: str) -> str:
    match = re.search(
        rf'^{re.escape(name)}\s*=\s*"([^"]+)"',
        PYPROJECT.read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    )
    assert match, name
    return match.group(1)


def test_exactly_one_skill_md_in_the_repository():
    found = [
        path
        for path in ROOT.rglob("SKILL.md")
        if not any(part in {".git", ".venv", "venv", "node_modules"} for part in path.parts)
    ]
    assert found == [SKILL]


def test_skill_frontmatter_name_matches_directory():
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    frontmatter = text.split("---\n", 2)[1]
    assert re.search(r"^name: supersearch$", frontmatter, flags=re.MULTILINE)
    assert re.search(r"^description: .+", frontmatter, flags=re.MULTILINE)


def test_agent_plugins_manifest_shape():
    manifest = _load("plugin.json")
    assert manifest["$schema"] == "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
    allowed = {
        "$schema", "name", "version", "description", "author", "homepage",
        "repository", "license", "keywords", "extensions",
    }
    assert set(manifest) <= allowed
    assert re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", manifest["name"])


def test_all_host_manifests_share_identity_with_pyproject():
    version = _pyproject("version")
    portable = _load("plugin.json")
    claude = _load(".claude-plugin/plugin.json")
    gemini = _load("gemini-extension.json")
    for manifest in (portable, claude, gemini):
        assert manifest["name"] == "supersearch"
        assert manifest["version"] == version
        assert manifest["description"] == portable["description"]
    assert claude["license"] == portable["license"] == _pyproject("license")


def test_marketplaces_resolve_to_the_repository_root():
    claude = _load(".claude-plugin/marketplace.json")
    (entry,) = claude["plugins"]
    assert entry["name"] == "supersearch"
    assert "version" not in entry
    assert (ROOT / entry["source"]).resolve() == ROOT

    codex = _load(".agents/plugins/marketplace.json")
    (entry,) = codex["plugins"]
    assert entry["name"] == "supersearch"
    assert entry["source"]["source"] == "local"
    assert (ROOT / entry["source"]["path"]).resolve() == ROOT


def test_skill_pins_the_released_package_and_uses_the_bounded_subcommand():
    text = SKILL.read_text(encoding="utf-8")
    version = _pyproject("version")
    specs = re.findall(r"hermes-supersearch==([0-9][^\s`\"']*)", text)
    assert specs and set(specs) == {version}
    assert not re.search(r"(?:uvx --from|pip install) hermes-supersearch(?!==)", text)
    assert f"/v{version}/docs/search-receipt-v1.schema.json" in text
    for command in re.findall(r"supersearch==[^\s]+ supersearch (\S+)", text):
        assert command == "search"
    for flag in ("--sources", "--max-per-source", "--deadline"):
        assert flag in text
