"""Tests for the CLI-facing formatters in supersearch.__main__."""

from supersearch.__main__ import format_markdown, format_result
from supersearch.search import SearchResult


def test_format_result_surfaces_provenance():
    r = SearchResult(title="T", url="https://x/1", snippet="s", sources=["ddg", "qwant"])
    out = format_result((r, 0.5), index=1)
    assert out["sources"] == ["ddg", "qwant"]
    assert out["rank"] == 1
    assert out["relevance_score"] == 0.5


def test_format_result_omits_sources_when_empty():
    r = SearchResult(title="T", url="https://x/1", snippet="s")
    out = format_result((r, 0.3), index=2)
    assert "sources" not in out


def test_format_markdown_renders_header_and_results():
    output = {
        "query": "test query",
        "total_results": 2,
        "summary": "A summary.",
        "results": [
            {
                "rank": 1,
                "relevance_score": 0.91,
                "title": "Title One",
                "url": "https://ex/1",
                "snippet": "Body one.",
                "sources": ["ddg", "qwant"],
            },
            {
                "rank": 2,
                "relevance_score": 0.42,
                "title": "Title Two",
                "url": "https://ex/2",
                "snippet": "Body two.",
            },
        ],
    }
    md = format_markdown(output)
    assert "# SuperSearch — test query" in md
    assert "## Summary" in md
    assert "A summary." in md
    assert "[Title One](https://ex/1)" in md
    assert "via ddg, qwant" in md  # provenance surfaced
    assert "> Body one." in md
    assert "[Title Two](https://ex/2)" in md


def test_format_markdown_handles_no_summary_or_extractions():
    output = {
        "query": "q",
        "total_results": 0,
        "results": [],
    }
    md = format_markdown(output)
    assert "# SuperSearch — q" in md
    # No Summary section when empty
    assert "## Summary" not in md


def test_format_markdown_renders_deep_extractions():
    output = {
        "query": "q",
        "total_results": 1,
        "results": [{"rank": 1, "relevance_score": 0.5, "title": "T", "url": "https://x/1", "snippet": "s"}],
        "deep_extractions": [
            {"title": "T", "url": "https://x/1", "extraction": "Key fact from page."}
        ],
    }
    md = format_markdown(output)
    assert "## Deep extractions" in md
    assert "Key fact from page." in md
