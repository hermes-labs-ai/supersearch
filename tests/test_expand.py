"""Tests for query expansion."""

from unittest.mock import MagicMock, patch

from supersearch import expand
from supersearch.search import SearchResult


def test_parse_variants_strips_numbering_and_dedupes():
    txt = """1. transformer architecture
- transformer model design
* attention mechanism
transformer architecture
"""
    out = expand._parse_variants(txt, original="transformer", max_variants=3)
    assert out == [
        "transformer architecture",
        "transformer model design",
        "attention mechanism",
    ]


def test_parse_variants_excludes_original():
    txt = "original query\nvariant one\nvariant two\n"
    out = expand._parse_variants(txt, original="original query")
    assert "original query" not in out
    assert out == ["variant one", "variant two"]


def test_parse_variants_limits_to_max():
    txt = "\n".join(f"v{i}" for i in range(10))
    out = expand._parse_variants(txt, original="x", max_variants=3)
    assert len(out) == 3


def test_parse_variants_strips_quotes():
    txt = '"quoted variant"\n\'single-quoted\'\n'
    out = expand._parse_variants(txt, original="x")
    assert out == ["quoted variant", "single-quoted"]


def test_expand_query_empty_returns_empty():
    assert expand.expand_query("") == []
    assert expand.expand_query("   ") == []


def test_expand_query_non_200_returns_empty():
    with patch("supersearch.expand.httpx.Client") as mock_client_cls:
        client = MagicMock()
        client.__enter__.return_value = client
        client.post.return_value.status_code = 500
        mock_client_cls.return_value = client
        assert expand.expand_query("anything") == []


def test_expand_query_success_returns_variants():
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "message": {"content": "variant one\nvariant two\nvariant three\n"}
    }
    with patch("supersearch.expand.httpx.Client") as mock_client_cls:
        client = MagicMock()
        client.__enter__.return_value = client
        client.post.return_value = fake_resp
        mock_client_cls.return_value = client
        out = expand.expand_query("original query")
    assert out == ["variant one", "variant two", "variant three"]


def test_expand_query_swallows_exceptions():
    with patch("supersearch.expand.httpx.Client", side_effect=RuntimeError("boom")):
        assert expand.expand_query("q") == []


def test_dedupe_results_dedupes_by_url_across_lists():
    a = SearchResult(title="A", url="https://x.com/1", snippet="")
    b = SearchResult(title="B", url="https://x.com/2", snippet="")
    c_dup = SearchResult(title="A-dup", url="https://x.com/1", snippet="")
    merged = expand.dedupe_results([[a, b], [c_dup]])
    assert [r.url for r in merged] == ["https://x.com/1", "https://x.com/2"]
