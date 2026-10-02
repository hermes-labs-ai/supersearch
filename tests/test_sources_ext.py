"""v0.10 round-3 connector tests.

Verify each connector:
  (a) is importable from supersearch.sources_ext
  (b) is registered in sources._source_map() under the expected key
  (c) its adapter converts a list[dict] to list[SearchResult] with URLs preserved
  (d) empty input / malformed items don't crash the adapter
"""

from __future__ import annotations

import time
from urllib.error import HTTPError

import pytest

from supersearch import sources
from supersearch.search import SearchResult
from supersearch import sources_ext
from supersearch.sources_ext import corp_signal_source, github_deep_source


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
    """The adapter converts the connector list[dict] contract to list[SearchResult]."""
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


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param([], id="empty-list"),
        pytest.param({"results": []}, id="empty-envelope"),
    ],
)
def test_adapter_valid_empty_results_are_completed(monkeypatch, raw):
    class _EmptySource:
        def search(self, query, max_results=5):
            return raw

    monkeypatch.setattr(
        sources,
        "_source_map",
        lambda: {"empty": sources._ext_result_adapter(_EmptySource)},
    )
    statuses = []

    results = sources.search_all(
        "q", sources=["empty"], parallel=False, source_statuses=statuses
    )

    assert results == []
    assert len(statuses) == 1
    assert statuses[0]["status"] == "completed"
    assert statuses[0]["result_count"] == 0
    assert statuses[0]["diagnostics"] == []


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param(None, id="none"),
        pytest.param({}, id="empty-envelope-missing-results"),
        pytest.param({"error": "upstream down"}, id="error-without-results"),
        pytest.param({"results": None}, id="none-results"),
        pytest.param({"results": "not-a-list"}, id="non-list-results"),
    ],
)
def test_adapter_malformed_results_are_failed(monkeypatch, raw):
    class _MalformedSource:
        def search(self, query, max_results=5):
            return raw

    monkeypatch.setattr(
        sources,
        "_source_map",
        lambda: {"malformed": sources._ext_result_adapter(_MalformedSource)},
    )
    statuses = []

    results = sources.search_all(
        "q", sources=["malformed"], parallel=False, source_statuses=statuses
    )

    assert results == []
    assert len(statuses) == 1
    assert statuses[0]["status"] == "failed"
    assert statuses[0]["result_count"] == 0
    assert any("invalid result data" in item for item in statuses[0]["diagnostics"])
    if raw == {"error": "upstream down"}:
        assert any("upstream down" in item for item in statuses[0]["diagnostics"])


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


def test_opencorp_error_record_marks_source_failed(monkeypatch):
    def unauthorized(*args, **kwargs):
        raise HTTPError("https://api.opencorporates.com", 401, "Unauthorized", {}, None)

    monkeypatch.setattr(corp_signal_source, "urlopen", unauthorized)
    statuses = []

    results = sources.search_all(
        "probe", sources=["opencorp"], parallel=False, source_statuses=statuses
    )

    assert results == []
    assert statuses[0]["status"] == "failed"
    assert "401" in statuses[0]["diagnostics"][0]


def test_github_deep_structured_result_is_adapted(monkeypatch):
    monkeypatch.setattr(
        sources_ext.GitHubDeepSource,
        "search",
        lambda self, query, max_results=5: {
            "results": [
                {
                    "title": "README: project",
                    "url": "https://github.com/example/project#readme",
                    "snippet": "project README",
                }
            ],
            "rate_limited": False,
        },
    )
    statuses = []

    results = sources.search_all(
        "probe", sources=["github_deep"], parallel=False, source_statuses=statuses
    )

    assert [result.url for result in results] == [
        "https://github.com/example/project#readme"
    ]
    assert statuses[0]["status"] == "completed"
    assert statuses[0]["result_count"] == 1


@pytest.mark.parametrize(
    "results, expected_status",
    [
        ([], "failed"),
        ([{"title": "Partial", "url": "https://github.com/example/project"}], "degraded"),
    ],
)
def test_github_deep_rate_limit_is_reported(monkeypatch, results, expected_status):
    monkeypatch.setattr(
        sources_ext.GitHubDeepSource,
        "search",
        lambda self, query, max_results=5: {
            "results": results,
            "rate_limited": True,
        },
    )
    statuses = []

    sources.search_all(
        "probe", sources=["github_deep"], parallel=False, source_statuses=statuses
    )

    assert statuses[0]["status"] == expected_status
    assert "rate limit" in statuses[0]["diagnostics"][0].lower()


def test_github_deep_missed_deadline_is_not_reported_as_empty_success(monkeypatch):
    def slow_search(self, query, max_results=5):
        time.sleep(0.2)
        return {"results": [], "rate_limited": False}

    monkeypatch.setattr(sources_ext.GitHubDeepSource, "search", slow_search)
    statuses = []

    sources.search_all(
        "probe",
        sources=["github_deep"],
        parallel=True,
        overall_timeout=0.01,
        source_statuses=statuses,
    )

    assert statuses[0]["status"] == "timed_out"


def test_github_deep_search_skips_nonexistent_wiki_contents_api(monkeypatch):
    calls = []

    class Response:
        status_code = 200

        def __init__(self, data):
            self.data = data

        def json(self):
            return self.data

        def raise_for_status(self):
            pass

    def get(url, **kwargs):
        calls.append(url)
        if url.endswith("/search/repositories"):
            return Response({"items": [
                {"owner": {"login": "example"}, "name": f"repo-{i}"}
                for i in range(3)
            ]})
        if url.endswith("/issues"):
            return Response([])
        if url.endswith("/readme"):
            return Response({"download_url": "https://example.com/readme"})
        raise AssertionError(f"unexpected GitHub endpoint: {url}")

    monkeypatch.setattr(github_deep_source.requests, "get", get)
    monkeypatch.setattr(github_deep_source.time, "sleep", lambda seconds: None)

    result = sources_ext.GitHubDeepSource().search("probe", max_results=10)

    assert len(result["results"]) == 3
    assert len(calls) == 7
    assert all("/contents/wiki" not in url for url in calls)


def test_github_deep_partial_request_failure_is_degraded(monkeypatch):
    class Response:
        def __init__(self, status_code, data=None):
            self.status_code = status_code
            self.data = data

        def json(self):
            return self.data

        def raise_for_status(self):
            pass

    def get(url, **kwargs):
        if url.endswith("/search/repositories"):
            return Response(200, {"items": [{
                "owner": {"login": "example"}, "name": "project"
            }]})
        if url.endswith("/issues"):
            return Response(503)
        if url.endswith("/readme"):
            return Response(200, {"download_url": "https://example.com/readme"})
        raise AssertionError(url)

    monkeypatch.setattr(github_deep_source.requests, "get", get)
    monkeypatch.setattr(github_deep_source.time, "sleep", lambda seconds: None)
    statuses = []

    results = sources.search_all(
        "probe", sources=["github_deep"], parallel=False, source_statuses=statuses
    )

    assert len(results) == 1
    assert statuses[0]["status"] == "degraded"
    assert "503" in statuses[0]["diagnostics"][0]


def test_github_deep_empty_search_is_completed(monkeypatch):
    class Response:
        status_code = 200

        def json(self):
            return {"items": []}

        def raise_for_status(self):
            pass

    monkeypatch.setattr(github_deep_source.requests, "get", lambda *args, **kwargs: Response())
    monkeypatch.setattr(github_deep_source.time, "sleep", lambda seconds: None)
    statuses = []

    results = sources.search_all(
        "probe", sources=["github_deep"], parallel=False, source_statuses=statuses
    )

    assert results == []
    assert statuses[0]["status"] == "completed"
    assert statuses[0]["diagnostics"] == []
