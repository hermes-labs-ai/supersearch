"""Tests for fact_audit — numeric contradictions + freshness per SCOPE.md."""

from __future__ import annotations

from datetime import datetime, timezone

from supersearch.search import SearchResult
from supersearch import fact_audit


def _r(title, snippet, url):
    return SearchResult(title=title, snippet=snippet, url=url)


def test_extract_facts_pulls_numeric_triples():
    results = [
        _r("Harvey AI news", "Harvey AI raised 80M in Series B funding.", "https://a.com/1"),
        _r("Open AI update", "OpenAI GPT-4 has 1.8 trillion parameters according to reports.", "https://b.com/2"),
    ]
    facts = fact_audit.extract_facts(results)
    # Must produce at least one fact per snippet
    assert len(facts) >= 2
    entities = {f.entity for f in facts if f.entity}
    assert "Harvey AI" in entities


def test_contradiction_flagged_on_twenty_percent_disagreement():
    # Two Harvey AI funding numbers: 80M and 100M → 25% spread, should flag.
    results = [
        _r("Harvey AI raise", "Harvey AI raised 80M Series B.", "https://a.com/1"),
        _r("Harvey AI funding", "Harvey AI announced 100M Series B round.", "https://b.com/2"),
    ]
    audit = fact_audit.audit(results)
    harvey = [c for c in audit.contradictions if c.entity.lower() == "harvey ai"]
    assert harvey, f"expected contradiction for Harvey AI, got {audit.contradictions}"
    assert harvey[0].span_ratio > 0.10


def test_contradiction_not_flagged_under_ten_percent():
    # 100 vs 105 → 5% spread, must NOT flag (SCOPE: >10% only).
    results = [
        _r("Harvey AI", "Harvey AI raised 100M Series B.", "https://a.com/1"),
        _r("Harvey AI update", "Harvey AI announced 105M round.", "https://b.com/2"),
    ]
    audit = fact_audit.audit(results)
    assert audit.contradictions == []


def test_freshness_score_bands():
    now = datetime(2026, 4, 18, tzinfo=timezone.utc)
    recent = datetime(2026, 4, 10, tzinfo=timezone.utc)          # 8 days → 1.0
    mid = datetime(2025, 10, 1, tzinfo=timezone.utc)             # ~200 days → 0.5
    old = datetime(2020, 1, 1, tzinfo=timezone.utc)              # >1yr → 0.0
    assert fact_audit.freshness_score(recent, now=now) == 1.0
    assert fact_audit.freshness_score(mid, now=now) == 0.5
    assert fact_audit.freshness_score(old, now=now) == 0.0
    assert fact_audit.freshness_score(None, now=now) == 0.0


def test_audit_writes_fact_audit_markdown_with_five_triples(tmp_path):
    results = [
        _r("Harvey AI 1", "Harvey AI raised 80M in 2024-11-05.", "https://a.com/1"),
        _r("Harvey AI 2", "Harvey AI announced 100M Series B on 2025-02-12.", "https://b.com/2"),
        _r("OpenAI GPT", "OpenAI GPT-4 has 1.8 trillion parameters per 2024-03-01 report.", "https://c.com/3"),
        _r("Corti raise", "Corti raised 60M Series B in 2024.", "https://d.com/4"),
        _r("Anthropic funding", "Anthropic raised 7.3B in 2025-04-01.", "https://e.com/5"),
    ]
    audit = fact_audit.audit(results)

    out = tmp_path / "fact-audit.md"
    fact_audit.write_audit_markdown(audit, str(out), query="AI funding news")
    body = out.read_text()

    # Gate: 5 (fact, URL, exact-quote) triples present
    assert body.count("**URL:**") >= 5
    assert body.count("**Quote:**") >= 5
    # Contradictions section exists
    assert "## Contradictions" in body
    # Freshness section exists
    assert "## Freshness" in body
