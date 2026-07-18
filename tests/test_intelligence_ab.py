"""A/B length-ratio gate for the intelligence layer (Task 3).

Runs ``run_search_core`` twice for the same query — once with intelligence
disabled, once enabled — using stubbed sources and a stubbed reranker so the
test is deterministic and offline. Confirms the JSON-output length ratio
falls inside SCOPE's 0.3–3.0 band and commits the diff sample to disk.
"""

from __future__ import annotations

import json

from supersearch.search import SearchResult  # noqa: F401
from supersearch import intelligence, rerank


def _stub_search_all(monkeypatch):
    """Make every 'engine' return 3 identical SearchResults so the A/B comparison
    only measures the effect of routing, not engine-level variance."""
    def fake_search_all(query, sources=None, max_per_source=3, **_kwargs):
        chosen = sources or ["ddg", "hn", "github", "twitter"]
        out = []
        for engine in chosen:
            for i in range(max_per_source):
                out.append(
                    SearchResult(
                        title=f"{engine} result {i} for {query}",
                        url=f"https://example.com/{engine}/{i}",
                        snippet=f"Snippet {i} from {engine} mentioning {query}",
                        sources=[engine],
                    )
                )
        return out

    monkeypatch.setattr("supersearch.intelligence.search_all", fake_search_all, raising=False)
    # Also patch the module-level import used inside run_search_core
    import supersearch.sources as _sources
    monkeypatch.setattr(_sources, "search_all", fake_search_all)


def _stub_reranker(monkeypatch):
    """Replace Ollama-backed reranker with a deterministic length-based score."""
    def fake_rerank(self, query, results, dedupe_snippets=True):
        ranked = [(r, 1.0 / (i + 1)) for i, r in enumerate(results)]
        return ranked

    monkeypatch.setattr(rerank.LocalReranker, "rerank", fake_rerank)


def _stub_routing(monkeypatch):
    """Force routing to return a known 3-engine subset so we can reason about output."""
    from supersearch import routing as _routing
    monkeypatch.setattr(_routing, "route", lambda q, **_kw: ["github", "hackernews", "searxng"])


def test_ab_length_ratio_within_band(monkeypatch, tmp_path):
    """Unit-level gate: stubbed A/B must keep its JSON length within the
    SCOPE 0.3–3.0 ratio band. The real-prose ab-sample.txt in the repo root
    is a separate artifact produced by scripts/gen_ab_sample.py against live
    qwen models — tests must NOT overwrite it."""
    _stub_search_all(monkeypatch)
    _stub_reranker(monkeypatch)
    _stub_routing(monkeypatch)

    query = "CVE 2024 remote code execution"

    out_a = intelligence.run_search_core(query, intelligence=False)
    out_b = intelligence.run_search_core(query, intelligence=True)

    len_a = len(json.dumps(out_a, indent=2))
    len_b = len(json.dumps(out_b, indent=2))
    ratio = len_b / len_a if len_a else 0.0

    # Write a per-run stub diff to tmp_path for debugging — NOT the committed artifact.
    (tmp_path / "ab-stub.txt").write_text(
        f"query={query}\nlen_a={len_a}\nlen_b={len_b}\nratio={ratio:.3f}\n"
    )

    assert 0.3 <= ratio <= 3.0, f"ratio {ratio} outside SCOPE band [0.3, 3.0]"


def test_intelligence_on_uses_routed_sources(monkeypatch):
    _stub_search_all(monkeypatch)
    _stub_reranker(monkeypatch)
    _stub_routing(monkeypatch)

    out = intelligence.run_search_core("CVE 2024 RCE", intelligence=True)
    assert out["intelligence"] is True
    assert out["sources_queried"] == ["github", "hackernews", "searxng"]


def test_intelligence_off_uses_default_sources(monkeypatch):
    _stub_search_all(monkeypatch)
    _stub_reranker(monkeypatch)
    _stub_routing(monkeypatch)

    out = intelligence.run_search_core("anything", intelligence=False)
    assert out["intelligence"] is False
    assert out["sources_queried"] == ["<default>"]
