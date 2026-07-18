"""Tests for the new scrapers: security.txt, arxiv abstract, HuggingFace."""

from unittest.mock import MagicMock, patch

import requests

from supersearch.scrapers import arxiv_abstract, huggingface_model, security_txt


# --- security.txt --------------------------------------------------------

def test_security_txt_normalize_adds_https():
    assert security_txt._normalize("example.com") == "https://example.com"


def test_security_txt_normalize_keeps_scheme():
    assert security_txt._normalize("http://example.com/foo").startswith("http://example.com")


def test_security_txt_parse_fields():
    txt = """# comment
Contact: mailto:security@example.com
Contact: https://example.com/report
Expires: 2027-01-01T00:00:00Z
Encryption: https://example.com/pgp.txt
Custom-Field: ignore-me-as-nonstandard
"""
    parsed = security_txt._parse(txt)
    assert parsed["contact"] == [
        "mailto:security@example.com",
        "https://example.com/report",
    ]
    assert parsed["expires"] == ["2027-01-01T00:00:00Z"]
    assert parsed["custom-field"] == ["ignore-me-as-nonstandard"]


def test_security_txt_fetch_success_wellknown():
    body = "Contact: mailto:security@example.com\nExpires: 2027-01-01T00:00:00Z\n"
    resp = MagicMock(status_code=200, text=body)

    def fake_get(url, **kw):
        # First call (well-known) returns 200 with body
        return resp

    with patch("supersearch.scrapers.security_txt.requests.get", side_effect=fake_get):
        result = security_txt.fetch("example.com")

    assert result["found"] is True
    assert result["domain"] == "example.com"
    assert "contact" in result["standard_fields"]
    assert result["url"].endswith("/.well-known/security.txt")


def test_security_txt_fetch_not_found_returns_structured_miss():
    resp = MagicMock(status_code=404, text="")
    with patch("supersearch.scrapers.security_txt.requests.get", return_value=resp):
        result = security_txt.fetch("example.com")
    assert result["found"] is False
    assert result["fields"] == {}


def test_security_txt_fetch_survives_request_exception():
    with patch(
        "supersearch.scrapers.security_txt.requests.get",
        side_effect=requests.ConnectionError("x"),
    ):
        result = security_txt.fetch("example.com")
    assert result["found"] is False
    assert "error" in result


# --- arxiv abstract ------------------------------------------------------

def test_arxiv_normalize_id_from_bare():
    assert arxiv_abstract._normalize_id("2501.12345") == "2501.12345"


def test_arxiv_normalize_id_from_url_with_version():
    assert arxiv_abstract._normalize_id("https://arxiv.org/abs/2501.12345v2") == "2501.12345v2"


def test_arxiv_normalize_id_returns_none_for_garbage():
    assert arxiv_abstract._normalize_id("banana") is None


ARXIV_FEED = b"""<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <title>Example Paper</title>
    <summary>We study X and find Y.</summary>
    <published>2025-01-15T00:00:00Z</published>
    <updated>2025-01-16T00:00:00Z</updated>
    <author><name>Alice</name></author>
    <author><name>Bob</name></author>
    <arxiv:primary_category term="cs.CL"/>
    <category term="cs.CL"/>
    <category term="cs.AI"/>
    <arxiv:doi>10.1234/example</arxiv:doi>
    <link rel="alternate" href="https://arxiv.org/abs/2501.12345"/>
    <link title="pdf" href="https://arxiv.org/pdf/2501.12345"/>
  </entry>
</feed>"""


def test_arxiv_fetch_parses_metadata():
    resp = MagicMock(status_code=200, content=ARXIV_FEED)
    resp.raise_for_status = MagicMock()
    with patch("supersearch.scrapers.arxiv_abstract.requests.get", return_value=resp):
        out = arxiv_abstract.fetch("2501.12345")
    assert out["title"] == "Example Paper"
    assert out["authors"] == ["Alice", "Bob"]
    assert out["doi"] == "10.1234/example"
    assert "cs.CL" in out["categories"]
    assert out["pdf_url"].endswith(".pdf") or out["pdf_url"].endswith("/2501.12345")


def test_arxiv_fetch_handles_bad_id():
    out = arxiv_abstract.fetch("not an id")
    assert "error" in out


def test_arxiv_fetch_handles_request_exception():
    with patch(
        "supersearch.scrapers.arxiv_abstract.requests.get",
        side_effect=requests.Timeout(),
    ):
        out = arxiv_abstract.fetch("2501.12345")
    assert "error" in out


# --- HuggingFace model card ---------------------------------------------

def test_hf_normalize_bare():
    assert huggingface_model._normalize_id("Qwen/Qwen2.5-7B") == "Qwen/Qwen2.5-7B"


def test_hf_normalize_url():
    assert huggingface_model._normalize_id(
        "https://huggingface.co/Qwen/Qwen2.5-7B-Instruct/tree/main"
    ) == "Qwen/Qwen2.5-7B-Instruct"


def test_hf_fetch_success():
    api_payload = {
        "author": "Qwen",
        "pipeline_tag": "text-generation",
        "library_name": "transformers",
        "downloads": 123456,
        "likes": 42,
        "createdAt": "2024-01-01",
        "lastModified": "2025-01-01",
        "tags": ["license:apache-2.0", "text-generation"],
        "cardData": {
            "license": "apache-2.0",
            "language": ["en", "zh"],
            "datasets": ["some/dataset"],
            "base_model": "Qwen/Qwen2.5-7B",
        },
    }
    api_resp = MagicMock(status_code=200)
    api_resp.json.return_value = api_payload
    readme_resp = MagicMock(status_code=200, text="# Model card\nBody")

    def fake_get(url, **kw):
        if "/api/models/" in url:
            return api_resp
        return readme_resp

    with patch("supersearch.scrapers.huggingface_model.requests.get", side_effect=fake_get):
        out = huggingface_model.fetch("Qwen/Qwen2.5-7B-Instruct")

    assert out["model_id"] == "Qwen/Qwen2.5-7B-Instruct"
    assert out["downloads"] == 123456
    assert out["license"] == "apache-2.0"
    assert out["languages"] == ["en", "zh"]
    assert out["readme"].startswith("# Model card")


def test_hf_fetch_bad_id():
    out = huggingface_model.fetch("no-slash")
    assert "error" in out


def test_hf_fetch_404():
    resp = MagicMock(status_code=404)
    with patch("supersearch.scrapers.huggingface_model.requests.get", return_value=resp):
        out = huggingface_model.fetch("nobody/nothing")
    assert "error" in out
    assert "not found" in out["error"].lower()


def test_hf_license_falls_back_to_tags():
    api_resp = MagicMock(status_code=200)
    api_resp.json.return_value = {
        "tags": ["license:mit"],
        "cardData": {},
    }
    readme_resp = MagicMock(status_code=404, text="")

    def fake_get(url, **kw):
        return api_resp if "/api/models/" in url else readme_resp

    with patch("supersearch.scrapers.huggingface_model.requests.get", side_effect=fake_get):
        out = huggingface_model.fetch("x/y")
    assert out["license"] == "mit"
