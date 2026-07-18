"""T3: supersearch.research — fan-out + multi-hop + parallel fetch + analyze.

Four required cases per spec:
  1. expand_fallback          — expand_query returning [] still runs
  2. multi_hop_activates      — depth=1 issues entity-based follow-ups
  3. output_layout            — expected files land in out_dir
  4. six_sections_present     — analysis.md has all 6 sections in order
"""

from __future__ import annotations

from supersearch import research as rmod
from supersearch.fact_audit import FactAudit, Fact
from supersearch.search import SearchResult


def _make_result(title, url, snippet="", sources=None):
    return SearchResult(title=title, url=url, snippet=snippet, sources=sources or ["ddg"])


def _stub_pipeline(monkeypatch, *, expand=None, entities=None, fetch_text="body ipsum"):
    """Neuter every network/local-model seam in research.py so the test runs
    deterministically in <1s."""
    # expand_query → variants or []
    monkeypatch.setattr(rmod, "expand_query", lambda q, max_variants=6, timeout=None: expand or [])

    # routing.route → fixed
    monkeypatch.setattr(rmod, "route", lambda q: ["ddg"])

    # search_all → 2 fake results per query, url-keyed on query so dedupe still exercises
    call_log: list[str] = []

    def fake_search_all(query, sources=None, max_per_source=3):
        call_log.append(query)
        base = query.replace(" ", "-")
        return [
            _make_result(f"{query} result 1", f"https://ex.com/{base}/1", f"snippet for {query}"),
            _make_result(f"{query} result 2", f"https://ex.com/{base}/2", f"another snippet {query}"),
        ]

    monkeypatch.setattr(rmod, "search_all", fake_search_all)

    # fact_audit.audit → force known entities so multi-hop fires
    def fake_audit(records):
        facts = [
            Fact(fact=f"{ent} claim", url="https://ex.com/e", exact_quote=f"{ent} claim",
                 entity=ent, value=100.0, unit="m", date=None)
            for ent in (entities or [])
        ]
        return FactAudit(facts=facts, contradictions=[], freshness_mean=0.75)

    monkeypatch.setattr(rmod, "audit", fake_audit)

    # LocalReranker — stable ordering
    class _FakeReranker:
        def rerank(self, topic, records):
            return [(r, 1.0 / (i + 1)) for i, r in enumerate(records)]

    monkeypatch.setattr(rmod, "LocalReranker", _FakeReranker)

    # DuckDuckGoSearch().fetch_content → fixed non-empty text
    class _FakeFetcher:
        def fetch_content(self, url, timeout=10, max_chars=0):
            return f"{fetch_text} for {url}" if fetch_text else None

    monkeypatch.setattr(rmod, "DuckDuckGoSearch", lambda: _FakeFetcher())

    # summarize_with_ollama → fixed prose
    monkeypatch.setattr(
        rmod,
        "summarize_with_ollama",
        lambda topic, payload, model="qwen3:14b": {"answer": f"stub summary for {topic}"},
    )

    return call_log


def test_expand_fallback(tmp_path, monkeypatch):
    """When expand_query returns [], pipeline still runs with [topic]-padded variants."""
    calls = _stub_pipeline(monkeypatch, expand=[])
    out = tmp_path / "out"
    result = rmod.run_research("test topic", depth=0, max_pages=3, out_dir=str(out))

    # At minimum, the topic string itself must have been queried
    assert "test topic" in calls
    assert result["variants_count"] >= 3  # padded to min
    assert result["pages_written"] >= 1
    assert (out / "analysis.md").exists()


def test_multi_hop_activates(tmp_path, monkeypatch):
    """depth=1 with entities present → second-pass 'topic entity' queries fire."""
    calls = _stub_pipeline(monkeypatch, expand=["variant A"], entities=["Harvey AI", "Anthropic"])
    out = tmp_path / "out"
    rmod.run_research("funding 2026", depth=1, max_pages=5, out_dir=str(out))

    # Multi-hop should have issued 'funding 2026 Harvey AI' and 'funding 2026 Anthropic'
    assert any("Harvey AI" in c for c in calls), calls
    assert any("Anthropic" in c for c in calls), calls


def test_output_layout(tmp_path, monkeypatch):
    """After a run, all expected files exist in out_dir."""
    _stub_pipeline(monkeypatch, expand=["va", "vb"])
    out = tmp_path / "layout"
    rmod.run_research("layout topic", depth=0, max_pages=4, out_dir=str(out))

    assert (out / "analysis.md").exists()
    assert (out / "corpus.jsonl").exists()
    assert (out / "STATUS.md").exists()
    assert (out / "pages").is_dir()
    assert len(list((out / "pages").glob("*.txt"))) >= 1


def test_six_sections_present(tmp_path, monkeypatch):
    """analysis.md contains the 6 required sections, in order, at ## level."""
    _stub_pipeline(monkeypatch, expand=["v1"])
    out = tmp_path / "six"
    rmod.run_research("section check", depth=0, max_pages=3, out_dir=str(out))

    body = (out / "analysis.md").read_text()
    required = [
        "# Research: section check",
        "## Summary",
        "## Top Entities",
        "## Freshness",
        "## Contradictions",
        "## Variants used",
        "## Sources",
    ]
    last_pos = -1
    for header in required:
        pos = body.find(header)
        assert pos > last_pos, f"missing or out-of-order: {header!r}"
        last_pos = pos
