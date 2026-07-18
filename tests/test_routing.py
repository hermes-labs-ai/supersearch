"""Tests for supersearch.routing — engine-category routing per SCOPE.md."""

import pytest

from supersearch import routing


@pytest.fixture(autouse=True)
def _bypass_reachability(monkeypatch):
    """Neuter the SearXNG reachability probe so unit tests exercise pure
    routing logic. Tests that explicitly want the probe can override this."""
    monkeypatch.setattr(routing, "_UNREACHABLE", set())


def _fake_embedder(vectors: dict[str, list[float]]):
    """Return an embed_fn that looks up pre-computed vectors by text.

    Unknown text gets a neutral orthogonal vector so cosine is ~0.
    """
    def _embed(text: str):
        return vectors.get(text, [0.0, 0.0, 1.0])  # orthogonal-ish default
    return _embed


def test_academic_query_routes_to_arxiv_and_semantic_scholar():
    """Gate: single-category ≥0.7 → top-3 engines for that category."""
    # Query and academic seed share a direction (cos ≈ 1.0). Others are
    # orthogonal (cos ≈ 0).
    vectors = {
        "transformer attention mechanism paper": [1.0, 0.0, 0.0],
        routing.CATEGORY_SEEDS["academic"]: [1.0, 0.0, 0.0],
        routing.CATEGORY_SEEDS["company"]: [0.0, 1.0, 0.0],
        routing.CATEGORY_SEEDS["security"]: [0.0, 1.0, 0.0],
        routing.CATEGORY_SEEDS["news"]: [0.0, 1.0, 0.0],
        routing.CATEGORY_SEEDS["general"]: [0.0, 1.0, 0.0],
    }
    engines = routing.route(
        "transformer attention mechanism paper",
        embed_fn=_fake_embedder(vectors),
    )
    # academic category has 2 engines ([arxiv, semantic_scholar]); top-3 caps
    # at available engines.
    assert engines == ["arxiv", "semantic_scholar"], engines


def test_low_confidence_falls_back_to_all_engines():
    """Gate: no category ≥0.7 → return ALL engines (existing behavior)."""
    # All seeds orthogonal to query → every cosine is 0.
    vectors = {
        "xyzzy plugh foobar": [1.0, 0.0, 0.0],
        routing.CATEGORY_SEEDS["academic"]: [0.0, 1.0, 0.0],
        routing.CATEGORY_SEEDS["company"]: [0.0, 1.0, 0.0],
        routing.CATEGORY_SEEDS["security"]: [0.0, 1.0, 0.0],
        routing.CATEGORY_SEEDS["news"]: [0.0, 1.0, 0.0],
        routing.CATEGORY_SEEDS["general"]: [0.0, 1.0, 0.0],
    }
    engines = routing.route(
        "xyzzy plugh foobar",
        embed_fn=_fake_embedder(vectors),
    )
    # Must include engines drawn from multiple categories — i.e. the union.
    assert "arxiv" in engines        # academic
    assert "github" in engines       # company/security
    assert "qwant" in engines        # general
    assert "hackernews" in engines   # news/security
    # Deduped: searxng appears in 4 categories but only once in the list.
    assert engines.count("searxng") == 1


def test_searxng_filtered_when_unreachable(monkeypatch):
    """Down-weight gate: when SearXNG is probed as down, it disappears from
    the routed list — but CATEGORY_ENGINES itself is unchanged so restoring
    the service doesn't need a code edit."""
    monkeypatch.setattr(routing, "_UNREACHABLE", {"searxng"})
    # Force the fallback path (all engines) so searxng would appear absent the filter.
    vectors = {
        "xyzzy plugh foobar": [1.0, 0.0, 0.0],
        routing.CATEGORY_SEEDS["academic"]: [0.0, 1.0, 0.0],
        routing.CATEGORY_SEEDS["company"]: [0.0, 1.0, 0.0],
        routing.CATEGORY_SEEDS["security"]: [0.0, 1.0, 0.0],
        routing.CATEGORY_SEEDS["news"]: [0.0, 1.0, 0.0],
        routing.CATEGORY_SEEDS["general"]: [0.0, 1.0, 0.0],
    }
    engines = routing.route(
        "xyzzy plugh foobar",
        embed_fn=_fake_embedder(vectors),
    )
    assert "searxng" not in engines
    # CATEGORY_ENGINES must still list searxng — the filter is runtime-only.
    assert "searxng" in {e for eng_list in routing.CATEGORY_ENGINES.values() for e in eng_list}


def test_multi_category_union_dedupes_and_caps_at_five():
    """Gate: 2+ categories ≥0.7 → union top-2 from each, dedupe, cap at 5."""
    # Make security and company BOTH score high. Their top-2 engines are
    # [github, hackernews] and [github, searxng] respectively — union should
    # dedupe github and keep order.
    vectors = {
        "startup disclosed CVE last week": [1.0, 0.0, 0.0],
        routing.CATEGORY_SEEDS["security"]: [1.0, 0.0, 0.0],   # cos=1.0
        routing.CATEGORY_SEEDS["company"]: [1.0, 0.0, 0.0],    # cos=1.0
        routing.CATEGORY_SEEDS["academic"]: [0.0, 1.0, 0.0],   # cos=0
        routing.CATEGORY_SEEDS["news"]: [0.0, 1.0, 0.0],       # cos=0
        routing.CATEGORY_SEEDS["general"]: [0.0, 1.0, 0.0],    # cos=0
    }
    engines = routing.route(
        "startup disclosed CVE last week",
        embed_fn=_fake_embedder(vectors),
    )
    # Union of security top-2 {github, hackernews} + company top-2 {github, searxng}
    # = {github, hackernews, searxng}, preserving first-seen order.
    assert len(engines) <= routing.MAX_ENGINES
    assert len(engines) == len(set(engines)), f"dupes in {engines}"
    assert set(engines) == {"github", "hackernews", "searxng"}, engines
