"""v0.10 round-3 connector tests.

Verify each connector:
  (a) is importable from supersearch.sources_ext
  (b) is registered in sources._source_map() under the expected key
  (c) its adapter converts a list[dict] to list[SearchResult] with URLs preserved
  (d) empty input / malformed items don't crash the adapter
"""

from __future__ import annotations

import pytest

from supersearch import sources
from supersearch.search import SearchResult
from supersearch import sources_ext


EXPECTED_KEYS = {"eurlex", "lexology", "ssrn", "github_deep", "opencorp", "edgar"}


def test_all_connectors_importable():
    """Every v0.10 connector class is exported from supersearch.sources_ext."""
    for name in ("EurLexSource", "LexologySource", "SSRNSource",
                 "GitHubDeepSource", "OpenCorporatesSource", "SECEdgarSource"):
        assert hasattr(sources_ext, name), f"missing export: {name}"


def test_all_connectors_registered():
    """_source_map() exposes every v0.10 connector under the documented key."""
    m = sources._source_map()
    missing = EXPECTED_KEYS - set(m)
    assert not missing, f"missing from _source_map: {missing}"


def test_adapter_converts_dicts_to_searchresult(monkeypatch):
    """The adapter converts SIGMA's list[dict] contract to list[SearchResult]."""
    class _FakeDictSource:
        def search(self, query, max_results=5):
            return [
                {"title": "Doc A", "url": "https://eur-lex.europa.eu/a", "snippet": "snip A"},
                {"title": "Doc B", "url": "https://eur-lex.europa.eu/b", "snippet": "snip B"},
            ]

    Adapted = sources._ext_result_adapter(_FakeDictSource)
    results = Adapted().search("anything", max_results=2)
    assert len(results) == 2
    assert all(isinstance(r, SearchResult) for r in results)
    assert results[0].url == "https://eur-lex.europa.eu/a"
    assert results[0].title == "Doc A"
    assert results[1].snippet == "snip B"


def test_adapter_skips_items_without_url():
    """Items without a URL are dropped silently; empty dicts don't crash."""
    class _FakeBad:
        def search(self, query, max_results=5):
            return [
                {"title": "no url"},
                {},
                {"url": "", "title": "empty url"},
                {"url": "https://good.example/1", "title": "good", "snippet": "s"},
            ]

    Adapted = sources._ext_result_adapter(_FakeBad)
    results = Adapted().search("q")
    assert len(results) == 1
    assert results[0].url == "https://good.example/1"


def test_adapter_swallows_search_exceptions():
    """Adapter must never raise — parity with sibling sources (HN, GitHub, etc.)."""
    class _Broken:
        def search(self, query, max_results=5):
            raise RuntimeError("upstream down")

    Adapted = sources._ext_result_adapter(_Broken)
    results = Adapted().search("anything")
    assert results == []


def test_adapter_respects_max_results():
    """Adapter caps output at max_results."""
    class _Many:
        def search(self, query, max_results=5):
            return [
                {"url": f"https://example.com/{i}", "title": f"t{i}", "snippet": f"s{i}"}
                for i in range(20)
            ]

    Adapted = sources._ext_result_adapter(_Many)
    results = Adapted().search("q", max_results=3)
    assert len(results) == 3


@pytest.mark.parametrize("key", sorted(EXPECTED_KEYS))
def test_registered_connector_instantiates(key):
    """Every v0.10 engine key produces a callable .search() method when instantiated."""
    cls = sources._source_map()[key]
    instance = cls()
    assert callable(getattr(instance, "search", None))


def test_search_all_accepts_new_engine_keys(monkeypatch):
    """search_all routes v0.10 engine names into the adapter pipeline.

    We stub the adapter's underlying search to a no-op so this is offline/fast;
    the goal is to verify the integration seam, not re-test the adapter.
    """
    calls = []

    def fake_run_one(name, cls, q, mps, jitter_max=0.0):
        calls.append(name)
        return [], []

    monkeypatch.setattr(sources, "_run_one_source", fake_run_one)
    sources.search_all("probe", sources=["eurlex", "opencorp"], parallel=False)
    assert set(calls) == {"eurlex", "opencorp"}
