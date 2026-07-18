"""T3: NLI — parsing, failure handling, caching, aggregation."""

from __future__ import annotations

from pathlib import Path

import pytest
import requests

from supersearch.verify import nli


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    """Point the disk cache at a tmp dir so tests never touch real cached labels."""
    monkeypatch.setenv("CLAIM_VERIFIER_CACHE", str(tmp_path))
    yield


class _FakeResponse:
    def __init__(self, content: str, status: int = 200):
        self._content = content
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status={self.status_code}")

    def json(self):
        return {"message": {"content": self._content}}


def test_classify_parses_entail(monkeypatch):
    monkeypatch.setattr(nli.requests, "post", lambda *a, **kw: _FakeResponse("ENTAIL"))
    out = nli.classify("Claim C", "Source S", use_cache=False)
    assert out == "ENTAIL"


def test_classify_rejects_token_buried_in_prose(monkeypatch):
    monkeypatch.setattr(
        nli.requests,
        "post",
        lambda *a, **kw: _FakeResponse("Let me think... CONTRADICT seems right."),
    )
    out = nli.classify("Claim", "Source", use_cache=False)
    assert out == "NEUTRAL"


def test_classify_no_token_returns_neutral(monkeypatch):
    monkeypatch.setattr(
        nli.requests, "post", lambda *a, **kw: _FakeResponse("I don't know")
    )
    assert nli.classify("C", "S", use_cache=False) == "NEUTRAL"


def test_classify_network_failure_returns_neutral(monkeypatch):
    def boom(*a, **kw):
        raise requests.ConnectionError("ollama down")

    monkeypatch.setattr(nli.requests, "post", boom)
    assert nli.classify("C", "S", use_cache=False) == "NEUTRAL"


def test_classify_empty_snippet_is_neutral(monkeypatch):
    called = {"n": 0}

    def sentinel(*a, **kw):
        called["n"] += 1
        return _FakeResponse("ENTAIL")

    monkeypatch.setattr(nli.requests, "post", sentinel)
    assert nli.classify("C", "", use_cache=False) == "NEUTRAL"
    assert nli.classify("C", "   \n\t", use_cache=False) == "NEUTRAL"
    assert called["n"] == 0, "empty snippet should short-circuit before ollama"


def test_classify_uses_cache(monkeypatch, tmp_path):
    calls = {"n": 0}

    def fake_post(*a, **kw):
        calls["n"] += 1
        return _FakeResponse("ENTAIL")

    monkeypatch.setattr(nli.requests, "post", fake_post)

    # First call — hits network, writes cache.
    a1 = nli.classify("Claim X", "Snippet Y", use_cache=True)
    # Second call with identical args — MUST come from cache.
    a2 = nli.classify("Claim X", "Snippet Y", use_cache=True)

    assert a1 == a2 == "ENTAIL"
    assert calls["n"] == 1, f"expected 1 network call, got {calls['n']}"
    # Cache file physically exists
    cache_files = list(Path(tmp_path).rglob("*.json"))
    assert len(cache_files) == 1


def test_batch_cache_cannot_bypass_unavailable_model(monkeypatch):
    key = nli._cache_key("Claim X", "Snippet Y", nli.DEFAULT_MODEL)
    nli._cache_put(key, "ENTAIL")
    monkeypatch.setattr(nli, "probe_model", lambda **kw: "model_unavailable")

    results = nli.classify_batch_results("Claim X", ["Snippet Y"])

    assert results[0].label == "NEUTRAL"
    assert results[0].status == "model_unavailable"


def test_batch_marks_missing_model_unavailable(monkeypatch):
    monkeypatch.setattr(nli, "probe_model", lambda **kw: "model_missing")
    results = nli.classify_batch_results("Claim", ["Evidence"])
    assert results == [
        nli.ClassificationResult("NEUTRAL", "model_missing", nli.DEFAULT_MODEL)
    ]


# ---- aggregation -------------------------------------------------------------


def test_aggregate_empty_is_unverified():
    assert nli.aggregate([]) == "UNVERIFIED"


def test_aggregate_all_neutral_is_unverified():
    assert nli.aggregate(["NEUTRAL"] * 5) == "UNVERIFIED"


def test_aggregate_majority_entail_is_supported():
    assert nli.aggregate(["ENTAIL", "ENTAIL", "ENTAIL", "NEUTRAL"]) == "SUPPORTED"


def test_aggregate_majority_contradict_is_contradicted():
    assert nli.aggregate(["CONTRADICT", "CONTRADICT", "NEUTRAL"]) == "CONTRADICTED"


def test_aggregate_split_is_conflicting():
    # 2 entail, 2 contradict — neither side dominant
    assert (
        nli.aggregate(["ENTAIL", "ENTAIL", "CONTRADICT", "CONTRADICT"]) == "CONFLICTING"
    )


def test_aggregate_dominant_with_small_dissent_is_still_dominant():
    # 4 entail + 1 contradict = 5 non-neutral; contradict share = 0.2 (== min share) → CONFLICTING
    assert nli.aggregate(["ENTAIL"] * 4 + ["CONTRADICT"]) == "CONFLICTING", (
        "5th dissenter at exactly the threshold should trip CONFLICTING"
    )


def test_aggregate_large_dominant_beats_tiny_dissent():
    # 9 entail + 1 contradict = 10; contradict share = 0.1 (< 0.2) → SUPPORTED
    assert nli.aggregate(["ENTAIL"] * 9 + ["CONTRADICT"]) == "SUPPORTED"


# ---- parsing -----------------------------------------------------------------


def test_parse_label_handles_edge_cases():
    assert nli._parse_label("") == "NEUTRAL"
    assert nli._parse_label("entail") == "ENTAIL"  # case-insensitive
    assert nli._parse_label("\n  NEUTRAL  \n") == "NEUTRAL"
    assert nli._parse_label("garbage") == "NEUTRAL"
    assert nli._parse_label("ENTAIL CONTRADICT") == "NEUTRAL"


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
