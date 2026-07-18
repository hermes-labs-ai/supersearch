"""T2: retrieval layer — verify HTML stripping, dedup, capping, failure behavior.

v0.9 additions: three fan-out tests (variants generated, cross-variant dedup,
empty-expand fallback) at the bottom of this file.
"""

from __future__ import annotations

import threading

import pytest

from supersearch.verify import retrieval


class _FakeResult:
    """Duck-type for supersearch SearchResult (title/url/snippet/raw_content/sources)."""

    def __init__(self, title, url, snippet, raw_content="", sources=None):
        self.title = title
        self.url = url
        self.snippet = snippet
        self.raw_content = raw_content
        self.sources = sources or []
        self.query_variant = ""


@pytest.fixture(autouse=True)
def _no_expand(monkeypatch):
    """By default in this module, suppress the v0.9 expand_query network call
    so existing tests stay deterministic. Individual fan-out tests override
    this fixture via direct monkeypatch."""
    monkeypatch.setattr(retrieval, "_expand_claim", lambda _c, **_kw: [])


def test_retrieve_strips_html_and_respects_cap(monkeypatch):
    fakes = [
        _FakeResult(
            "Real &amp; Good <b>Title</b>",
            "https://news.ycombinator.com/a",
            "<em>Highlight</em>: 1.8 <b>trillion</b> parameters &mdash; said someone.",
            sources=["ddg", "hn"],
        ),
        _FakeResult(
            "Second",
            "https://news.ycombinator.com/b",
            "<p>Claim B with   whitespace\n\nand tags</p>",
            sources=["bing"],
        ),
        _FakeResult("Third", "https://news.ycombinator.com/c", "third snippet"),
        _FakeResult("Fourth", "https://news.ycombinator.com/d", "fourth snippet"),
    ]
    monkeypatch.setattr(retrieval, "_route_engines", lambda _claim: ["ddg"])
    monkeypatch.setattr(
        "supersearch.sources.search_all",
        lambda *a, **kw: fakes,
    )

    out = retrieval.retrieve("any claim", max_sources=3)

    assert len(out) == 3, "max_sources cap not respected"
    first = out[0]
    assert first.title == "Real & Good Title", (
        f"HTML entities not decoded: {first.title!r}"
    )
    assert "<" not in first.snippet and ">" not in first.snippet
    assert "1.8" in first.snippet and "trillion" in first.snippet
    assert first.engines == ["ddg", "hn"]
    # raw_content absent → empty string, not None
    assert first.raw_content == ""


def test_retrieve_dedupes_urls(monkeypatch):
    fakes = [
        _FakeResult("A", "https://news.ycombinator.com/dup", "one"),
        _FakeResult("A again", "https://news.ycombinator.com/dup", "two"),
        _FakeResult("B", "https://news.ycombinator.com/other", "three"),
    ]
    monkeypatch.setattr(retrieval, "_route_engines", lambda _claim: [])
    monkeypatch.setattr("supersearch.sources.search_all", lambda *a, **kw: fakes)

    out = retrieval.retrieve("any", max_sources=10)

    assert len(out) == 2
    assert {r.url for r in out} == {
        "https://news.ycombinator.com/dup",
        "https://news.ycombinator.com/other",
    }


def test_retrieve_returns_empty_on_failure(monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("network is down")

    monkeypatch.setattr(retrieval, "_route_engines", lambda _claim: [])
    monkeypatch.setattr("supersearch.sources.search_all", boom)

    out = retrieval.retrieve("any claim")
    assert out == []


def test_retrieval_status_distinguishes_failure_from_no_sources(monkeypatch):
    monkeypatch.setattr(retrieval, "_route_engines", lambda _claim: [])
    monkeypatch.setattr("supersearch.sources.search_all", lambda *a, **kw: [])
    assert retrieval.retrieve_with_status("none").status == "no_sources"

    def boom(*a, **kw):
        raise RuntimeError("network unavailable")

    monkeypatch.setattr("supersearch.sources.search_all", boom)
    assert retrieval.retrieve_with_status("failed").status == "unavailable"


def test_swallowed_source_error_marks_partial_retrieval(monkeypatch):
    monkeypatch.setattr(retrieval, "_route_engines", lambda _claim: ["ddg", "hn"])

    def partial(*a, **kw):
        kw["diagnostics"].append("hn: HN search error: network unavailable")
        return [
            _FakeResult(
                "Surviving result",
                "https://news.ycombinator.com/survivor",
                "partial evidence",
                sources=["ddg"],
            )
        ]

    monkeypatch.setattr("supersearch.sources.search_all", partial)
    result = retrieval.retrieve_with_status("claim")
    assert result.status == "partial"
    assert len(result.records) == 1
    assert result.failed_queries == ["claim"]


def test_retrieved_as_dict_shape():
    r = retrieval.Retrieved(
        title="t",
        url="https://news.ycombinator.com/x",
        snippet="s",
        raw_content="rc",
        engines=["ddg"],
        query_variant="alt phrase",
    )
    d = r.as_dict()
    assert set(d.keys()) == {
        "title",
        "url",
        "snippet",
        "raw_content",
        "engines",
        "query_variant",
    }
    assert d["engines"] == ["ddg"]
    assert d["query_variant"] == "alt phrase"


def test_clean_handles_none_and_entities():
    # Private helper but central to the contract — exercise it directly.
    assert retrieval._clean(None) == ""
    assert retrieval._clean("") == ""
    assert retrieval._clean("<p>hi &amp; bye</p>") == "hi & bye"


def test_default_engine_selection_has_no_model_or_ddgs_dependency():
    engines = retrieval._route_engines("any claim")

    assert engines == list(retrieval.VERIFY_DEFAULT_ENGINES)
    assert "ddg" not in engines
    assert "twitter" not in engines


# ---------------------------------------------------------------------------
# v0.9 fan-out tests
# ---------------------------------------------------------------------------


def test_retrieve_fans_out_variants(monkeypatch):
    """expand_query returning 2 variants should trigger 3 search_all calls
    (base claim + 2 variants), and each unique URL should carry the variant
    that first surfaced it."""
    monkeypatch.setattr(retrieval, "_route_engines", lambda _c: ["ddg"])
    monkeypatch.setattr(
        retrieval,
        "_expand_claim",
        lambda _c, **_kw: ["alt phrase one", "narrower angle"],
    )

    calls: list[str] = []
    per_query = {
        "base claim": [
            _FakeResult("A", "https://news.ycombinator.com/a", "a1", sources=["ddg"])
        ],
        "alt phrase one": [
            _FakeResult("B", "https://news.ycombinator.com/b", "b1", sources=["bing"])
        ],
        "narrower angle": [
            _FakeResult("C", "https://news.ycombinator.com/c", "c1", sources=["mojeek"])
        ],
    }

    def fake_search_all(q, **_kw):
        calls.append(q)
        return per_query.get(q, [])

    monkeypatch.setattr("supersearch.sources.search_all", fake_search_all)

    out = retrieval.retrieve("base claim", max_sources=10)

    assert sorted(calls) == ["alt phrase one", "base claim", "narrower angle"]
    assert len(out) == 3
    variants_by_url = {r.url: r.query_variant for r in out}
    assert variants_by_url["https://news.ycombinator.com/a"] == "base claim"
    assert variants_by_url["https://news.ycombinator.com/b"] == "alt phrase one"
    assert variants_by_url["https://news.ycombinator.com/c"] == "narrower angle"


def test_variant_fanout_remains_concurrent(monkeypatch):
    monkeypatch.setattr(retrieval, "_route_engines", lambda _c: ["ddg"])
    monkeypatch.setattr(
        retrieval, "_expand_claim", lambda _c, **_kw: ["variant one", "variant two"]
    )
    barrier = threading.Barrier(3)

    def fake_search_all(query, **_kw):
        barrier.wait(timeout=1)
        return [
            _FakeResult(
                query,
                f"https://news.ycombinator.com/{query.replace(' ', '-')}",
                query,
                sources=["ddg"],
            )
        ]

    monkeypatch.setattr("supersearch.sources.search_all", fake_search_all)
    result = retrieval.retrieve_with_status("base claim")
    assert result.status == "ok"
    assert len(result.records) == 3


def test_retrieve_dedupes_across_variants(monkeypatch):
    """Same URL from two variants → one record, engines merged, variant =
    first-seen (claim)."""
    monkeypatch.setattr(retrieval, "_route_engines", lambda _c: ["ddg"])
    monkeypatch.setattr(retrieval, "_expand_claim", lambda _c, **_kw: ["variant one"])

    per_query = {
        "base": [
            _FakeResult(
                "X", "https://news.ycombinator.com/x", "from base", sources=["ddg"]
            ),
        ],
        "variant one": [
            _FakeResult(
                "X-alt",
                "https://news.ycombinator.com/x",
                "from variant",
                sources=["bing"],
            ),
            _FakeResult(
                "Y", "https://news.ycombinator.com/y", "uniquely y", sources=["mojeek"]
            ),
        ],
    }

    def fake_search_all(q, **_kw):
        return per_query.get(q, [])

    monkeypatch.setattr("supersearch.sources.search_all", fake_search_all)

    out = retrieval.retrieve("base", max_sources=10)

    urls = {r.url for r in out}
    assert urls == {"https://news.ycombinator.com/x", "https://news.ycombinator.com/y"}

    by_url = {r.url: r for r in out}
    x = by_url["https://news.ycombinator.com/x"]
    # Claim variant wins since it was inserted first (results_by_variant is
    # re-keyed in claim-first order before the merge).
    assert x.query_variant == "base"
    assert set(x.engines) == {"ddg", "bing"}


def test_retrieve_fallback_when_expand_empty(monkeypatch):
    """expand returns []; only one search_all call happens; every result's
    query_variant is the base claim."""
    monkeypatch.setattr(retrieval, "_route_engines", lambda _c: ["ddg"])
    monkeypatch.setattr(retrieval, "_expand_claim", lambda _c, **_kw: [])

    calls: list[str] = []

    def fake_search_all(q, **_kw):
        calls.append(q)
        return [
            _FakeResult("Z", "https://news.ycombinator.com/z", "z1", sources=["ddg"])
        ]

    monkeypatch.setattr("supersearch.sources.search_all", fake_search_all)

    out = retrieval.retrieve("lonely claim", max_sources=10)

    assert calls == ["lonely claim"]
    assert len(out) == 1
    assert out[0].query_variant == "lonely claim"


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
