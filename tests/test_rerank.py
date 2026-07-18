"""Tests for the local reranker."""

from unittest.mock import MagicMock, patch

from supersearch import rerank as rerank_mod
from supersearch.rerank import (
    LocalReranker,
    dedupe_by_snippet,
    domain_authority,
    extract_year,
    freshness_signal,
    snippet_fingerprint,
)
from supersearch.search import SearchResult


def _mk_resp(embedding):
    r = MagicMock(status_code=200)
    r.json.return_value = {"embeddings": [embedding]}
    r.raise_for_status = MagicMock()
    return r


def test_cosine_similarity_identical_is_one():
    r = LocalReranker()
    v = [1.0, 0.0, 0.0]
    assert abs(r._cosine_similarity(v, v) - 1.0) < 1e-9


def test_cosine_similarity_orthogonal_is_zero():
    r = LocalReranker()
    assert r._cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_cosine_similarity_zero_vectors_returns_zero():
    r = LocalReranker()
    assert r._cosine_similarity([0.0, 0.0], [0.0, 0.0]) == 0.0


def test_rerank_empty_input_returns_empty():
    assert LocalReranker().rerank("q", []) == []


def test_rerank_orders_by_similarity_to_query():
    reranker = LocalReranker()
    # Query embedding ≈ [1, 0]. First result [1, 0] (identical). Second [0, 1].
    seq = iter([
        _mk_resp([1.0, 0.0]),   # query
        _mk_resp([0.0, 1.0]),   # r1 (low sim)
        _mk_resp([1.0, 0.0]),   # r2 (high sim)
    ])
    with patch("supersearch.rerank.requests.post", side_effect=lambda *a, **k: next(seq)):
        r1 = SearchResult("r1", "https://x/1", "")
        r2 = SearchResult("r2", "https://x/2", "")
        out = reranker.rerank("q", [r1, r2])
    assert [x[0].url for x in out] == ["https://x/2", "https://x/1"]
    assert out[0][1] > out[1][1]


def test_rerank_preserves_count_when_query_embed_fails():
    reranker = LocalReranker()
    r1 = SearchResult("r1", "https://x/1", "")
    r2 = SearchResult("r2", "https://x/2", "")
    with patch("supersearch.rerank.requests.post", side_effect=RuntimeError("no ollama")):
        out = reranker.rerank("q", [r1, r2])
    assert len(out) == 2
    # Fallback score blends freshness+authority (no semantic), must be consistent.
    # Both results have same authority (0.5) and same freshness (0.3), so scores match.
    assert all(abs(score - out[0][1]) < 1e-9 for _, score in out)


# --- extract_year --------------------------------------------------------

def test_extract_year_finds_most_recent_in_range():
    assert extract_year("Published 2024 or maybe 2022") == 2024


def test_extract_year_picks_iso_date():
    assert extract_year("posted 2025-03-14 by author") == 2025


def test_extract_year_ignores_out_of_range():
    # 1899 too old, 2999 too new
    assert extract_year("from 1899 or 2999") is None


def test_extract_year_scans_url_too():
    assert extract_year("no date", url="https://blog.example.com/2026/hello") == 2026


def test_extract_year_returns_none_when_empty():
    assert extract_year("", url="") is None


# --- freshness_signal ----------------------------------------------------

def test_freshness_current_year_is_one():
    assert freshness_signal("article 2026", now_year=2026) == 1.0


def test_freshness_one_year_old_is_high():
    assert freshness_signal("posted 2025", now_year=2026) == 0.85


def test_freshness_unknown_year_is_neutral_low():
    # No year found — small but non-zero so unknown doesn't dominate.
    assert freshness_signal("no date here", now_year=2026) == 0.3


def test_freshness_decays_to_zero_for_ancient():
    # 10 years old → clamped at 0
    assert freshness_signal("from 2016", now_year=2026) == 0.0


# --- domain_authority ----------------------------------------------------

def test_authority_exact_domain_hit():
    assert domain_authority("https://arxiv.org/abs/1234") == 1.0
    assert domain_authority("https://github.com/x/y") == 0.90


def test_authority_parent_domain_hit():
    # Subdomain like en.wikipedia.org maps to wikipedia.org (or en.wikipedia.org directly).
    assert domain_authority("https://en.wikipedia.org/wiki/X") >= 0.9


def test_authority_edu_gov_fallback():
    assert domain_authority("https://cs.stanford.edu/paper") == 0.80
    assert domain_authority("https://nist.gov/report") == 0.85


def test_authority_unknown_domain_is_neutral():
    assert domain_authority("https://some-random-blog.example.com/") == 0.5


def test_authority_malformed_url_is_neutral():
    assert domain_authority("not-a-url") == 0.5
    assert domain_authority("") == 0.5


# --- snippet_fingerprint + dedupe_by_snippet ----------------------------

def test_snippet_fingerprint_is_case_insensitive_and_whitespace_insensitive():
    a = snippet_fingerprint("Hello   World  ")
    b = snippet_fingerprint("hello world")
    assert a == b


def test_snippet_fingerprint_empty_is_empty():
    assert snippet_fingerprint("") == ""


def test_dedupe_drops_identical_snippets_across_urls():
    r1 = SearchResult("t1", "https://a/1", "Same body of text.")
    r2 = SearchResult("t2", "https://b/2", "Same body of text.")
    out = dedupe_by_snippet([(r1, 0.9), (r2, 0.4)])
    assert [x[0].url for x in out] == ["https://a/1"]  # highest-scored copy wins


def test_dedupe_keeps_results_with_empty_snippets():
    r1 = SearchResult("t1", "https://a/1", "")
    r2 = SearchResult("t2", "https://b/2", "")
    out = dedupe_by_snippet([(r1, 0.5), (r2, 0.5)])
    assert len(out) == 2  # unhashable snippets never collide


# --- Composite score wiring ---------------------------------------------

def test_composite_score_weights_sum_to_one():
    assert abs(
        rerank_mod.W_SEMANTIC + rerank_mod.W_FRESHNESS + rerank_mod.W_AUTHORITY - 1.0
    ) < 1e-9


def test_rerank_applies_authority_bonus_on_tied_semantic(monkeypatch):
    """Two results with identical semantic similarity: arxiv.org wins via authority."""
    reranker = LocalReranker()
    # All embeddings identical so semantic sim == 1.0 for both
    seq = iter([
        _mk_resp([1.0, 0.0]),  # query
        _mk_resp([1.0, 0.0]),  # r1 (arxiv)
        _mk_resp([1.0, 0.0]),  # r2 (random blog)
    ])
    with patch("supersearch.rerank.requests.post", side_effect=lambda *a, **k: next(seq)):
        r1 = SearchResult("arxiv paper", "https://arxiv.org/abs/1234", "about X")
        r2 = SearchResult("random blog", "https://some-random-blog.example.com/", "about X")
        out = reranker.rerank("X", [r1, r2])
    # arxiv should rank first despite identical semantic score
    assert out[0][0].url == "https://arxiv.org/abs/1234"


def test_rerank_dedupes_snippet_duplicates(monkeypatch):
    reranker = LocalReranker()
    seq = iter([
        _mk_resp([1.0, 0.0]),  # query
        _mk_resp([1.0, 0.0]),  # r1
        _mk_resp([1.0, 0.0]),  # r2 (same snippet, diff URL)
    ])
    with patch("supersearch.rerank.requests.post", side_effect=lambda *a, **k: next(seq)):
        r1 = SearchResult("t", "https://a/1", "Identical snippet body.")
        r2 = SearchResult("t", "https://b/2", "Identical snippet body.")
        out = reranker.rerank("q", [r1, r2])
    assert len(out) == 1


def test_rerank_dedupe_can_be_disabled(monkeypatch):
    reranker = LocalReranker()
    seq = iter([
        _mk_resp([1.0, 0.0]),
        _mk_resp([1.0, 0.0]),
        _mk_resp([1.0, 0.0]),
    ])
    with patch("supersearch.rerank.requests.post", side_effect=lambda *a, **k: next(seq)):
        r1 = SearchResult("t", "https://a/1", "Identical snippet body.")
        r2 = SearchResult("t", "https://b/2", "Identical snippet body.")
        out = reranker.rerank("q", [r1, r2], dedupe_snippets=False)
    assert len(out) == 2
