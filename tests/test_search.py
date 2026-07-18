"""Tests for DuckDuckGoSearch + fetch_content."""

from unittest.mock import MagicMock, patch


from supersearch.search import DuckDuckGoSearch, SearchResult


def _mk_ddg_result(title, url, body):
    return {"title": title, "href": url, "body": body}


def test_search_returns_structured_results(tmp_cache_dir):
    mock_ddgs = MagicMock()
    mock_ddgs.text.return_value = iter([
        _mk_ddg_result("t1", "https://a.example", "b1"),
        _mk_ddg_result("t2", "https://b.example", "b2"),
    ])
    s = DuckDuckGoSearch(use_cache=False)
    s.ddgs = mock_ddgs
    results = s.search("hello", max_results=5)
    assert len(results) == 2
    assert isinstance(results[0], SearchResult)
    assert results[0].title == "t1"
    assert results[0].url == "https://a.example"
    assert results[0].snippet == "b1"


def test_search_returns_empty_on_exception(tmp_cache_dir):
    mock_ddgs = MagicMock()
    mock_ddgs.text.side_effect = RuntimeError("down")
    s = DuckDuckGoSearch(use_cache=False)
    s.ddgs = mock_ddgs
    assert s.search("anything") == []


def test_search_writes_and_reads_cache(tmp_cache_dir, monkeypatch):
    from supersearch import cache as _cache

    monkeypatch.setattr(_cache, "DEFAULT_CACHE_DIR", tmp_cache_dir)

    call_count = {"n": 0}

    def fake_text(q, max_results, backend):
        call_count["n"] += 1
        return iter([_mk_ddg_result("t", "https://x.example", "b")])

    s = DuckDuckGoSearch(use_cache=True)
    s.ddgs.text = fake_text  # type: ignore[assignment]

    first = s.search("my query", max_results=3)
    second = s.search("my query", max_results=3)

    assert call_count["n"] == 1  # second call served from cache
    assert [r.url for r in first] == [r.url for r in second]
    assert first[0].title == "t"


def test_search_no_cache_flag_bypasses_cache(tmp_cache_dir, monkeypatch):
    from supersearch import cache as _cache

    monkeypatch.setattr(_cache, "DEFAULT_CACHE_DIR", tmp_cache_dir)

    call_count = {"n": 0}

    def fake_text(q, max_results, backend):
        call_count["n"] += 1
        return iter([_mk_ddg_result("t", "https://x.example", "b")])

    s = DuckDuckGoSearch(use_cache=False)
    s.ddgs.text = fake_text  # type: ignore[assignment]

    s.search("q", max_results=3)
    s.search("q", max_results=3)
    assert call_count["n"] == 2  # no caching


def test_fetch_content_strips_scripts_and_styles():
    html = b"""
    <html><head><title>t</title><style>body{}</style></head>
    <body>
      <script>evil();</script>
      <nav>nav</nav>
      <p>Real content here.</p>
      <footer>footer</footer>
    </body></html>
    """
    mock_resp = MagicMock(text=html.decode(), status_code=200)
    mock_resp.raise_for_status = MagicMock()

    s = DuckDuckGoSearch(use_cache=False)
    with patch("supersearch.search.requests.get", return_value=mock_resp):
        text = s.fetch_content("https://x.example")
    assert "Real content here." in text
    assert "evil" not in text
    assert "nav" not in text
    assert "footer" not in text


def test_fetch_content_returns_none_on_exception():
    s = DuckDuckGoSearch(use_cache=False)
    with patch("supersearch.search.requests.get", side_effect=RuntimeError("x")):
        assert s.fetch_content("https://x.example") is None


def test_fetch_content_respects_max_chars():
    big = "<html><body>" + ("x" * 50000) + "</body></html>"
    mock_resp = MagicMock(text=big, status_code=200)
    mock_resp.raise_for_status = MagicMock()
    s = DuckDuckGoSearch(use_cache=False)
    with patch("supersearch.search.requests.get", return_value=mock_resp):
        text = s.fetch_content("https://x.example", max_chars=100)
    assert text is not None
    assert len(text) <= 100
