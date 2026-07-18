"""Tests for each search source + parallel search_all orchestrator."""

import time
from unittest.mock import MagicMock, patch

import requests

from supersearch import sources
from supersearch.search import SearchResult


# --- _trim_query ---------------------------------------------------------


def test_trim_query_keeps_short_unchanged():
    assert sources._trim_query("short query", 5) == "short query"


def test_trim_query_drops_stop_words_over_threshold():
    out = sources._trim_query(
        "what are the best LLM security tools for enterprise",
        max_keywords=4,
    )
    # stop words (what, are, the, for) dropped
    assert "the" not in out.split()
    assert "what" not in out.split()
    assert len(out.split()) <= 4


def test_trim_query_falls_back_when_all_stop_words():
    q = "what is the this that"
    # All stop-words, so fallback keeps original
    assert sources._trim_query(q, max_keywords=2) == q


# --- HackerNewsSearch ----------------------------------------------------


def test_hn_search_parses_algolia_hits():
    hn = sources.HackerNewsSearch()
    fake_hits = {
        "hits": [
            {
                "objectID": "123",
                "title": "A title",
                "points": 42,
                "num_comments": 5,
                "author": "pg",
            },
            {"objectID": "456", "comment_text": "some comment text here"},
        ]
    }
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = fake_hits
    mock_resp.raise_for_status = MagicMock()
    with patch("supersearch.sources.requests.get", return_value=mock_resp):
        results = hn.search("show hn")
    assert len(results) == 2
    assert results[0].url == "https://news.ycombinator.com/item?id=123"
    assert "42 pts" in results[0].snippet


def test_hn_search_returns_empty_on_timeout():
    hn = sources.HackerNewsSearch()
    with patch("supersearch.sources.requests.get", side_effect=requests.Timeout()):
        assert hn.search("x") == []


def test_hn_search_returns_empty_on_http_error():
    hn = sources.HackerNewsSearch()
    with patch("supersearch.sources.requests.get", side_effect=RuntimeError("nope")):
        assert hn.search("x") == []


# --- GitHubSearch --------------------------------------------------------


def test_github_search_parses_repos():
    gh = sources.GitHubSearch()
    fake = {
        "items": [
            {
                "full_name": "org/repo",
                "html_url": "https://github.com/org/repo",
                "stargazers_count": 100,
                "description": "a thing",
            },
        ]
    }
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = fake
    mock_resp.raise_for_status = MagicMock()
    with patch("supersearch.sources.requests.get", return_value=mock_resp):
        results = gh.search("tool")
    assert results[0].title == "org/repo"
    assert "100" in results[0].snippet


def test_github_search_handles_empty_items():
    gh = sources.GitHubSearch()
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = {"items": []}
    mock_resp.raise_for_status = MagicMock()
    with patch("supersearch.sources.requests.get", return_value=mock_resp):
        assert gh.search("x") == []


# --- ArxivSearch ---------------------------------------------------------

ARXIV_ATOM = b"""<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Sample Title</title>
    <summary>An abstract about transformers.</summary>
    <id>http://arxiv.org/abs/2501.12345v1</id>
  </entry>
</feed>"""


def test_arxiv_search_parses_atom():
    ax = sources.ArxivSearch()
    mock_resp = MagicMock(status_code=200, content=ARXIV_ATOM)
    mock_resp.raise_for_status = MagicMock()
    with patch("supersearch.sources.requests.get", return_value=mock_resp):
        results = ax.search("transformers")
    assert len(results) == 1
    assert results[0].title == "Sample Title"
    assert results[0].url.startswith("https://arxiv.org/abs/")


def test_arxiv_search_returns_empty_on_error():
    ax = sources.ArxivSearch()
    with patch("supersearch.sources.requests.get", side_effect=RuntimeError("x")):
        assert ax.search("x") == []


# --- SemanticScholarSearch ----------------------------------------------


def test_semantic_scholar_parses_papers():
    ss = sources.SemanticScholarSearch()
    fake = {
        "data": [
            {
                "title": "Attention is All You Need",
                "url": "https://example.org/paper",
                "year": 2017,
                "citationCount": 99999,
                "authors": [{"name": "A"}, {"name": "B"}],
                "abstract": "A transformer paper.",
            }
        ]
    }
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = fake
    mock_resp.raise_for_status = MagicMock()
    with patch("supersearch.sources.requests.get", return_value=mock_resp):
        results = ss.search("attention")
    assert results[0].title == "Attention is All You Need"
    assert "99999" in results[0].snippet


# --- search_all orchestrator --------------------------------------------


class _FakeSource:
    """Deterministic fake source used across orchestrator tests."""

    calls = []

    def __init__(self, *, name, results=None, exc=None, delay=0.0):
        self._name = name
        self._results = results or []
        self._exc = exc
        self._delay = delay

    def search(self, query, max_results):
        if self._delay:
            time.sleep(self._delay)
        _FakeSource.calls.append((self._name, query, max_results))
        if self._exc is not None:
            raise self._exc
        return self._results


def _register_fake_sources(monkeypatch, mapping):
    def _smap():
        return mapping

    monkeypatch.setattr(sources, "_source_map", _smap)


def test_search_all_combines_and_dedupes(monkeypatch):
    _FakeSource.calls = []
    a = _FakeSource(
        name="ddg",
        results=[
            SearchResult("A1", "https://x/1", ""),
            SearchResult("A2", "https://x/2", ""),
        ],
    )
    b = _FakeSource(
        name="hn",
        results=[
            SearchResult("B1", "https://x/2", ""),
            SearchResult("B3", "https://x/3", ""),
        ],
    )

    class _AFactory:
        def __call__(self):
            return a

    class _BFactory:
        def __call__(self):
            return b

    _register_fake_sources(monkeypatch, {"ddg": _AFactory(), "hn": _BFactory()})
    out = sources.search_all("q", sources=["ddg", "hn"], parallel=False)
    urls = [r.url for r in out]
    assert urls == ["https://x/1", "https://x/2", "https://x/3"]


def test_search_all_one_source_raising_does_not_kill_others(monkeypatch):
    good = _FakeSource(name="ddg", results=[SearchResult("A", "https://x/1", "")])
    bad = _FakeSource(name="hn", exc=RuntimeError("boom"))
    _register_fake_sources(
        monkeypatch,
        {"ddg": lambda: good, "hn": lambda: bad},
    )
    diagnostics = []
    out = sources.search_all(
        "q", sources=["ddg", "hn"], parallel=False, diagnostics=diagnostics
    )
    assert [r.url for r in out] == ["https://x/1"]
    assert any("hn:" in message and "boom" in message for message in diagnostics)


def test_search_all_structures_completed_empty_and_failed_sources(monkeypatch):
    empty = _FakeSource(name="ddg", results=[])
    bad = _FakeSource(name="hn", exc=RuntimeError("network down"))
    _register_fake_sources(
        monkeypatch,
        {"ddg": lambda: empty, "hn": lambda: bad},
    )
    statuses = []

    out = sources.search_all(
        "q",
        sources=["ddg", "hn", "missing"],
        parallel=False,
        source_statuses=statuses,
    )

    assert out == []
    assert statuses == [
        {
            "name": "ddg",
            "status": "completed",
            "result_count": 0,
            "diagnostics": [],
        },
        {
            "name": "hn",
            "status": "failed",
            "result_count": 0,
            "diagnostics": ["Error from hn: network down"],
        },
        {
            "name": "missing",
            "status": "unsupported",
            "result_count": 0,
            "diagnostics": ["source name is not registered"],
        },
    ]


def test_search_all_parallel_matches_serial_output(monkeypatch):
    a = _FakeSource(name="ddg", results=[SearchResult("A", "https://x/1", "")])
    b = _FakeSource(name="hn", results=[SearchResult("B", "https://x/2", "")])
    _register_fake_sources(monkeypatch, {"ddg": lambda: a, "hn": lambda: b})
    serial = sources.search_all("q", sources=["ddg", "hn"], parallel=False)
    parallel = sources.search_all("q", sources=["ddg", "hn"], parallel=True)
    assert [r.url for r in serial] == [r.url for r in parallel]


def test_search_all_parallel_is_faster_than_serial(monkeypatch):
    # Two slow sources (0.4s each). Serial ~0.8s, parallel ~0.4s.
    a = _FakeSource(
        name="ddg", results=[SearchResult("A", "https://x/1", "")], delay=0.4
    )
    b = _FakeSource(
        name="hn", results=[SearchResult("B", "https://x/2", "")], delay=0.4
    )
    _register_fake_sources(monkeypatch, {"ddg": lambda: a, "hn": lambda: b})

    t0 = time.time()
    sources.search_all("q", sources=["ddg", "hn"], parallel=False)
    serial = time.time() - t0

    t0 = time.time()
    sources.search_all("q", sources=["ddg", "hn"], parallel=True)
    par = time.time() - t0

    # Parallel must be faster than 0.7x the serial run.
    assert par < serial * 0.7, (
        f"parallel={par:.2f}s not faster than serial={serial:.2f}s"
    )


def test_search_all_unknown_source_is_skipped(monkeypatch):
    a = _FakeSource(name="ddg", results=[SearchResult("A", "https://x/1", "")])
    _register_fake_sources(monkeypatch, {"ddg": lambda: a})
    out = sources.search_all("q", sources=["ddg", "nope"], parallel=True)
    assert [r.url for r in out] == ["https://x/1"]


def test_search_all_hung_source_respects_timeout_budget(monkeypatch):
    """A source that hangs far past the budget must not stall search_all.

    Regression for the ``--source=all`` hang: a stuck source used to be joined
    at ``ThreadPoolExecutor.__exit__`` and blow past ``overall_timeout``
    (observed >120s in the field). The daemon-thread + wall-clock-deadline
    design must return within the budget and still surface the fast source.
    """
    fast = _FakeSource(name="ddg", results=[SearchResult("A", "https://x/1", "")])
    # 1000s "hang" — orders of magnitude past the 1s budget below.
    hung = _FakeSource(
        name="hn", results=[SearchResult("B", "https://x/2", "")], delay=1000
    )
    _register_fake_sources(monkeypatch, {"ddg": lambda: fast, "hn": lambda: hung})

    t0 = time.monotonic()
    diagnostics = []
    statuses = []
    out = sources.search_all(
        "q",
        sources=["ddg", "hn"],
        parallel=True,
        overall_timeout=1,
        diagnostics=diagnostics,
        source_statuses=statuses,
    )
    elapsed = time.monotonic() - t0

    # Budget held: returned near the 1s deadline, nowhere near the 1000s hang.
    assert elapsed < 3, f"search_all blocked {elapsed:.1f}s past its 1s budget"
    # Fast source surfaced; hung source abandoned.
    assert [r.url for r in out] == ["https://x/1"]
    assert any(
        "timeout" in message.lower() and "hn" in message for message in diagnostics
    )
    assert statuses[0]["status"] == "completed"
    assert statuses[1] == {
        "name": "hn",
        "status": "timed_out",
        "result_count": 0,
        "diagnostics": ["missed the 1s overall search deadline"],
    }


def test_search_all_default_leaves_score_none_and_order_unchanged(monkeypatch):
    """Default (rerank=False) is byte-identical: retrieval order, score=None."""
    a = _FakeSource(
        name="ddg",
        results=[
            SearchResult("A", "https://x/1", ""),
            SearchResult("B", "https://x/2", ""),
        ],
    )
    _register_fake_sources(monkeypatch, {"ddg": lambda: a})
    out = sources.search_all("q", sources=["ddg"], parallel=False)
    assert [r.url for r in out] == ["https://x/1", "https://x/2"]
    assert all(r.score is None for r in out)


def test_search_all_rerank_populates_and_sorts_by_score(monkeypatch):
    """rerank=True populates SearchResult.score and returns descending order."""
    a = _FakeSource(
        name="ddg",
        results=[
            SearchResult("A", "https://x/1", ""),
            SearchResult("B", "https://x/2", ""),
        ],
    )
    _register_fake_sources(monkeypatch, {"ddg": lambda: a})

    # Deterministic reranker (no Ollama dependency): reverse order, descending
    # scores, so we can assert both annotation and re-ordering.
    import supersearch.rerank as rerank_mod

    class _FakeReranker:
        def __init__(self, *args, **kwargs):
            pass

        def rerank(self, query, results, dedupe_snippets=True):
            n = len(results)
            return [(r, float(n - i)) for i, r in enumerate(reversed(results))]

    monkeypatch.setattr(rerank_mod, "LocalReranker", _FakeReranker)

    out = sources.search_all("q", sources=["ddg"], parallel=False, rerank=True)
    # Every result carries a score.
    assert all(r.score is not None for r in out)
    # Sorted descending by score.
    assert [r.score for r in out] == sorted((r.score for r in out), reverse=True)
    # Reranker reordered (B now first).
    assert [r.url for r in out] == ["https://x/2", "https://x/1"]


def test_search_all_rerank_failure_returns_unranked(monkeypatch):
    """A reranker error must not break search — return unranked results."""
    a = _FakeSource(name="ddg", results=[SearchResult("A", "https://x/1", "")])
    _register_fake_sources(monkeypatch, {"ddg": lambda: a})

    import supersearch.rerank as rerank_mod

    class _BoomReranker:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("ollama down")

    monkeypatch.setattr(rerank_mod, "LocalReranker", _BoomReranker)
    out = sources.search_all("q", sources=["ddg"], parallel=False, rerank=True)
    assert [r.url for r in out] == ["https://x/1"]
    assert out[0].score is None


def test_dedupe_by_url_drops_empty_urls():
    r1 = SearchResult("a", "", "")
    r2 = SearchResult("b", "https://x/1", "")
    r3 = SearchResult("c", "https://x/1", "")
    out = sources._dedupe_by_url([r1, r2, r3])
    assert [r.url for r in out] == ["https://x/1"]


# --- MarginaliaSearch ----------------------------------------------------


def test_marginalia_parses_results():
    m = sources.MarginaliaSearch()
    fake = {
        "results": [
            {
                "url": "https://small.example/page",
                "title": "A Small Page",
                "description": "Some text from a small website.",
            },
            {
                "url": "https://blog.example/post",
                "title": "Blog Post",
                "description": "Hand-written content.",
            },
        ]
    }
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = fake
    mock_resp.raise_for_status = MagicMock()
    with patch("supersearch.sources.requests.get", return_value=mock_resp):
        results = m.search("small web")
    assert len(results) == 2
    assert results[0].url == "https://small.example/page"
    assert "small website" in results[0].snippet


def test_marginalia_skips_results_without_url():
    m = sources.MarginaliaSearch()
    fake = {"results": [{"title": "no url"}, {"url": "https://x/1", "title": "ok"}]}
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = fake
    mock_resp.raise_for_status = MagicMock()
    with patch("supersearch.sources.requests.get", return_value=mock_resp):
        results = m.search("q")
    assert [r.url for r in results] == ["https://x/1"]


def test_marginalia_returns_empty_on_error():
    m = sources.MarginaliaSearch()
    with patch("supersearch.sources.requests.get", side_effect=RuntimeError("nope")):
        assert m.search("x") == []


# --- WibySearch ----------------------------------------------------------


def test_wiby_parses_results():
    w = sources.WibySearch()
    fake = [
        {"URL": "https://wiby.example/a", "Title": "A", "Snippet": "snippet a"},
        {"URL": "https://wiby.example/b", "Title": "B", "Snippet": "snippet b"},
    ]
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = fake
    mock_resp.raise_for_status = MagicMock()
    with patch("supersearch.sources.requests.get", return_value=mock_resp):
        results = w.search("hobby")
    assert [r.url for r in results] == [
        "https://wiby.example/a",
        "https://wiby.example/b",
    ]
    assert results[0].snippet == "snippet a"


def test_wiby_returns_empty_on_error():
    w = sources.WibySearch()
    with patch("supersearch.sources.requests.get", side_effect=RuntimeError("x")):
        assert w.search("x") == []


# --- _merge_with_provenance ---------------------------------------------


def test_merge_records_engine_provenance():
    by_source = {
        "ddg": [SearchResult("DDG title", "https://x/1", "ddg snippet")],
        "hn": [SearchResult("HN title", "https://x/1", "hn snippet")],
    }
    out = sources._merge_with_provenance(by_source)
    assert len(out) == 1
    assert out[0].url == "https://x/1"
    assert out[0].sources == ["ddg", "hn"]


def test_merge_stitches_snippets_from_different_engines():
    by_source = {
        "ddg": [SearchResult("t", "https://x/1", "first context")],
        "github": [SearchResult("t", "https://x/1", "second context")],
    }
    out = sources._merge_with_provenance(by_source)
    assert "first context" in out[0].snippet
    assert "second context" in out[0].snippet
    assert " | " in out[0].snippet


def test_merge_does_not_duplicate_identical_snippets():
    by_source = {
        "ddg": [SearchResult("t", "https://x/1", "same body")],
        "bing": [SearchResult("t", "https://x/1", "same body")],
    }
    out = sources._merge_with_provenance(by_source)
    assert out[0].snippet == "same body"  # not "same body | same body"


def test_merge_preserves_caller_source_order():
    by_source = {
        "first": [SearchResult("a", "https://x/1", "")],
        "second": [SearchResult("b", "https://x/2", "")],
        "third": [SearchResult("c", "https://x/3", "")],
    }
    out = sources._merge_with_provenance(by_source)
    assert [r.url for r in out] == ["https://x/1", "https://x/2", "https://x/3"]


def test_merge_skips_empty_urls():
    by_source = {
        "ddg": [
            SearchResult("a", "", "no url"),
            SearchResult("b", "https://x/1", "real"),
        ],
    }
    out = sources._merge_with_provenance(by_source)
    assert [r.url for r in out] == ["https://x/1"]


def test_search_all_now_returns_provenance(monkeypatch):
    a = _FakeSource(name="ddg", results=[SearchResult("A", "https://x/1", "from ddg")])
    b = _FakeSource(name="hn", results=[SearchResult("A", "https://x/1", "from hn")])
    _register_fake_sources(monkeypatch, {"ddg": lambda: a, "hn": lambda: b})
    out = sources.search_all("q", sources=["ddg", "hn"], parallel=False)
    assert len(out) == 1
    assert set(out[0].sources) == {"ddg", "hn"}


# --- QwantSearch ---------------------------------------------------------


def test_qwant_parses_mainline_web_group():
    q = sources.QwantSearch()
    fake = {
        "data": {
            "result": {
                "items": {
                    "mainline": [
                        {
                            "type": "web",
                            "items": [
                                {
                                    "url": "https://ex.com/a",
                                    "title": "A",
                                    "desc": "snippet a",
                                },
                                {
                                    "url": "https://ex.com/b",
                                    "title": "B",
                                    "desc": "snippet b",
                                },
                            ],
                        }
                    ]
                }
            }
        }
    }
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = fake
    mock_resp.raise_for_status = MagicMock()
    with patch("supersearch.sources.requests.get", return_value=mock_resp):
        results = q.search("privacy search", max_results=5)
    assert [r.url for r in results] == ["https://ex.com/a", "https://ex.com/b"]
    assert results[0].snippet == "snippet a"


def test_qwant_ignores_non_web_groups():
    q = sources.QwantSearch()
    fake = {
        "data": {
            "result": {
                "items": {
                    "mainline": [
                        {
                            "type": "news",
                            "items": [
                                {"url": "https://news/1", "title": "N", "desc": "news"}
                            ],
                        },
                        {
                            "type": "web",
                            "items": [
                                {"url": "https://web/1", "title": "W", "desc": "web"}
                            ],
                        },
                    ]
                }
            }
        }
    }
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = fake
    mock_resp.raise_for_status = MagicMock()
    with patch("supersearch.sources.requests.get", return_value=mock_resp):
        results = q.search("x")
    assert [r.url for r in results] == ["https://web/1"]


def test_qwant_returns_empty_on_error():
    q = sources.QwantSearch()
    with patch("supersearch.sources.requests.get", side_effect=RuntimeError("x")):
        assert q.search("x") == []


# --- EcosiaSearch --------------------------------------------------------

ECOSIA_HTML = """
<html><body><main>
  <article>
    <a data-test-id="result-link" href="https://example.org/one">First Title</a>
    <div class="result__description">First snippet body text.</div>
  </article>
  <article>
    <a data-test-id="result-link" href="https://example.org/two">Second Title</a>
    <div class="result__description">Second snippet body text.</div>
  </article>
</main></body></html>
"""


def test_ecosia_parses_result_articles():
    results = sources._parse_ecosia_html(ECOSIA_HTML, max_results=5)
    assert [r.url for r in results] == [
        "https://example.org/one",
        "https://example.org/two",
    ]
    assert results[0].title == "First Title"
    assert "First snippet" in results[0].snippet


def test_ecosia_search_handles_http_error():
    e = sources.EcosiaSearch()
    with patch(
        "supersearch.antidetect.request_with_retry", side_effect=RuntimeError("nope")
    ):
        assert e.search("x") == []


def test_ecosia_search_end_to_end_with_mocked_response():
    e = sources.EcosiaSearch()
    mock_resp = MagicMock(status_code=200, text=ECOSIA_HTML)
    mock_resp.raise_for_status = MagicMock()
    with patch("supersearch.antidetect.request_with_retry", return_value=mock_resp):
        results = e.search("small web", max_results=2)
    assert len(results) == 2
    assert results[0].url == "https://example.org/one"


def test_ecosia_parses_empty_html_without_crashing():
    assert sources._parse_ecosia_html("<html></html>") == []


# --- StartpageSearch -----------------------------------------------------

STARTPAGE_HTML = """
<html><body>
  <div class="w-gl__result">
    <a class="w-gl__result-url" href="https://hit.one/">Hit One</a>
    <p class="description">First description here.</p>
  </div>
  <div class="w-gl__result">
    <a class="w-gl__result-url" href="https://hit.two/">Hit Two</a>
    <p class="description">Second description here.</p>
  </div>
</body></html>
"""


def test_startpage_parses_results():
    results = sources._parse_startpage_html(STARTPAGE_HTML, max_results=5)
    assert [r.url for r in results] == ["https://hit.one/", "https://hit.two/"]
    assert results[0].title == "Hit One"
    assert "First description" in results[0].snippet


def test_startpage_search_end_to_end_with_mocked_response():
    s = sources.StartpageSearch()
    mock_resp = MagicMock(status_code=200, text=STARTPAGE_HTML)
    mock_resp.raise_for_status = MagicMock()
    with patch("supersearch.antidetect.request_with_retry", return_value=mock_resp):
        results = s.search("q", max_results=2)
    assert [r.url for r in results] == ["https://hit.one/", "https://hit.two/"]


def test_startpage_parses_empty_html_without_crashing():
    assert sources._parse_startpage_html("<html><body></body></html>") == []


def test_startpage_search_handles_http_error():
    s = sources.StartpageSearch()
    with patch(
        "supersearch.antidetect.request_with_retry", side_effect=RuntimeError("nope")
    ):
        assert s.search("x") == []


# --- _source_map registrations ------------------------------------------


def test_new_engines_registered_in_source_map():
    smap = sources._source_map()
    assert "qwant" in smap
    assert "ecosia" in smap
    assert "startpage" in smap
    assert smap["qwant"] is sources.QwantSearch
    assert smap["ecosia"] is sources.EcosiaSearch
    assert smap["startpage"] is sources.StartpageSearch
