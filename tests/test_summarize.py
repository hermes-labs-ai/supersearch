"""Tests for summarize.py."""

from unittest.mock import MagicMock, patch

from supersearch import summarize


def test_build_prompt_includes_all_results_numbered():
    results = [
        {"title": "T1", "url": "https://a", "snippet": "S1"},
        {"title": "T2", "url": "https://b", "snippet": "S2"},
    ]
    system, user = summarize.build_prompt("my query", results)
    assert "CONSTRAINTS" in system
    assert "[1] T1" in user
    assert "[2] T2" in user
    assert "my query" in user


def test_build_prompt_handles_missing_fields():
    results = [{}, {"title": "Has"}]
    _, user = summarize.build_prompt("q", results)
    assert "Untitled" in user
    assert "Has" in user


def test_summarize_with_haiku_subagent_returns_structured_dict():
    out = summarize.summarize_with_haiku_subagent("q", [{"title": "t", "url": "u", "snippet": "s"}])
    assert out["scaffold"] == "tierjump-guard-quickthink-v1"
    assert "anthropic/claude-haiku" in out["model"]
    assert "Based on the search results:" in out["task"]


def test_summarize_with_ollama_success():
    fake_resp = MagicMock(status_code=200)
    fake_resp.json.return_value = {"message": {"content": "concise answer"}}
    with patch("supersearch.summarize.httpx.Client") as cls:
        c = MagicMock()
        c.__enter__.return_value = c
        c.post.return_value = fake_resp
        cls.return_value = c
        out = summarize.summarize_with_ollama(
            "q", [{"title": "t", "url": "u", "snippet": "s"}]
        )
    assert out["cost"] == "$0.00 (local)"
    assert "concise answer" in out["answer"]
    assert out["answer"].startswith("Based on the search results:")


def test_summarize_with_ollama_non_200_returns_error():
    fake_resp = MagicMock(status_code=502)
    with patch("supersearch.summarize.httpx.Client") as cls:
        c = MagicMock()
        c.__enter__.return_value = c
        c.post.return_value = fake_resp
        cls.return_value = c
        out = summarize.summarize_with_ollama("q", [])
    assert "error" in out


def test_extract_with_ollama_success():
    fake_resp = MagicMock(status_code=200)
    fake_resp.json.return_value = {"message": {"content": "Name: Foo\nPrice: $9"}}
    with patch("supersearch.summarize.httpx.Client") as cls:
        c = MagicMock()
        c.__enter__.return_value = c
        c.post.return_value = fake_resp
        cls.return_value = c
        out = summarize.extract_with_ollama("q", "title", "https://u", "page body")
    assert out["url"] == "https://u"
    assert "Foo" in out["extraction"]
    assert out["cost"] == "$0.00 (local)"


def test_extract_with_ollama_non_200_returns_none():
    fake_resp = MagicMock(status_code=500)
    with patch("supersearch.summarize.httpx.Client") as cls:
        c = MagicMock()
        c.__enter__.return_value = c
        c.post.return_value = fake_resp
        cls.return_value = c
        assert summarize.extract_with_ollama("q", "t", "u", "p") is None
