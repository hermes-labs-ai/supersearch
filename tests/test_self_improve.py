"""Tests for the self-improvement loop."""



from supersearch import self_improve
from supersearch.search import SearchResult


class _StubSearcher:
    """Pluggable searcher: returns canned per-query results."""

    def __init__(self, table: dict[str, list[SearchResult]]):
        self.table = table
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        self.calls.append((query, max_results))
        return self.table.get(query, [])


def test_parse_triggers_detects_ua_rotation():
    rs = [SearchResult("Rotate User-Agent strings to evade bots", "https://a", "")]
    triggers = self_improve._parse_triggers(rs)
    assert "Rotate UA / IP / headers" in triggers
    assert triggers["Rotate UA / IP / headers"] == ["https://a"]


def test_parse_triggers_detects_candidate_engines():
    rs = [
        SearchResult("Marginalia search", "https://m", "small-web indexing"),
        SearchResult("Try Kagi for ad-free", "https://k", ""),
    ]
    triggers = self_improve._parse_triggers(rs)
    assert "Candidate engine to integrate" in triggers
    assert set(triggers["Candidate engine to integrate"]) == {"https://m", "https://k"}


def test_parse_triggers_returns_empty_when_no_match():
    rs = [SearchResult("totally unrelated weather news", "https://w", "rain forecast")]
    assert self_improve._parse_triggers(rs) == {}


def test_run_self_improve_writes_report(tmp_path):
    out = tmp_path / "logs" / "report.md"
    table = {
        "q1": [SearchResult("Rotate user-agent guide", "https://example/1", "rotate UA on every request")],
        "q2": [SearchResult("Marginalia API", "https://example/2", "small-web search")],
    }
    stub = _StubSearcher(table)
    result = self_improve.run_self_improve(
        output_path=str(out),
        queries=["q1", "q2"],
        searcher=stub,
    )
    assert out.exists()
    body = out.read_text()
    # Report has the headline sections
    assert "# SuperSearch self-improvement report" in body
    assert "## Queries" in body
    assert "## Triggers" in body
    # The two queries appear as section headers
    assert "`q1`" in body and "`q2`" in body
    # Triggers were detected and recorded
    assert "Rotate UA / IP / headers" in body
    assert "Candidate engine to integrate" in body
    assert result["queries_run"] == 2
    assert result["results_total"] == 2
    assert "Rotate UA / IP / headers" in result["triggers"]


def test_run_self_improve_swallows_per_query_errors(tmp_path):
    out = tmp_path / "report.md"

    class _BoomSearcher:
        def search(self, q, max_results=5):
            raise RuntimeError("api down")

    result = self_improve.run_self_improve(
        output_path=str(out),
        queries=["x", "y"],
        searcher=_BoomSearcher(),
    )
    assert out.exists()
    assert result["queries_run"] == 2
    assert result["results_total"] == 0
    assert result["triggers"] == {}


def test_run_self_improve_creates_parent_dirs(tmp_path):
    out = tmp_path / "deep" / "nested" / "report.md"
    self_improve.run_self_improve(
        output_path=str(out),
        queries=["q"],
        searcher=_StubSearcher({}),
    )
    assert out.exists()


def test_default_meta_queries_are_nonempty():
    assert len(self_improve.META_QUERIES) >= 5
    for q in self_improve.META_QUERIES:
        assert q.strip()
