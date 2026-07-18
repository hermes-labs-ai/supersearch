"""Shared test fixtures."""

import sys
from pathlib import Path

# Ensure src/ is importable without a pip install
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest  # noqa: E402 — after sys.path mutation above


def pytest_addoption(parser):
    """Register --intelligence to gate live Ollama-backed integration tests.

    Task 5 gate: ``pytest`` and ``pytest --intelligence`` must BOTH pass.
    Default runs the fast deterministic suite; ``--intelligence`` adds the
    end-to-end test that requires a running Ollama with nomic-embed-text.
    """
    parser.addoption(
        "--intelligence",
        action="store_true",
        default=False,
        help="Enable live intelligence integration tests (needs Ollama running)",
    )


def pytest_collection_modifyitems(config, items):
    """Skip tests marked ``intelligence_live`` unless ``--intelligence`` is given."""
    if config.getoption("--intelligence"):
        return
    skip_marker = pytest.mark.skip(reason="requires --intelligence (live Ollama)")
    for item in items:
        if "intelligence_live" in item.keywords:
            item.add_marker(skip_marker)


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "intelligence_live: requires --intelligence flag and live Ollama",
    )


@pytest.fixture
def tmp_cache_dir(tmp_path, monkeypatch):
    """Point the cache module at a tmp directory for this test."""
    from supersearch import cache as _cache

    d = tmp_path / "cache"
    monkeypatch.setattr(_cache, "DEFAULT_CACHE_DIR", str(d))
    return str(d)
