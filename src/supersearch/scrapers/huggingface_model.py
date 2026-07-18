"""
HuggingFace model-card scraper.

Fetches structured model metadata from the public HF API plus the raw
README.md (model card) from the repo. No auth required for public models.

Usage:
    python3 -m supersearch.scrapers.huggingface_model meta-llama/Llama-3.1-8B
    python3 -m supersearch.scrapers.huggingface_model https://huggingface.co/Qwen/Qwen2.5-7B-Instruct
"""

import json
import sys
from typing import Optional
from urllib.parse import urlparse

import requests


API_URL = "https://huggingface.co/api/models"
README_URL_FMT = "https://huggingface.co/{model_id}/raw/main/README.md"


def _normalize_id(raw: str) -> str:
    """Accept bare 'org/name' or any HF URL; return 'org/name'."""
    s = raw.strip().rstrip("/")
    if s.startswith(("http://", "https://")):
        path = urlparse(s).path.strip("/")
        # HF path looks like <org>/<name> possibly followed by /tree/main etc.
        parts = path.split("/")
        if len(parts) >= 2:
            return "/".join(parts[:2])
        return path
    return s


def fetch(model_id_or_url: str, timeout: int = 12, include_readme: bool = True) -> dict:
    """Fetch HF model metadata + README. Returns {'error': ...} on failure."""
    model_id = _normalize_id(model_id_or_url)
    if not model_id or "/" not in model_id:
        return {"error": f"could not parse model id from: {model_id_or_url}"}

    headers = {"User-Agent": "SuperSearch-HuggingFace/1.0"}
    try:
        resp = requests.get(f"{API_URL}/{model_id}", timeout=timeout, headers=headers)
    except requests.RequestException as e:
        return {"model_id": model_id, "error": f"api request failed: {e}"}

    if resp.status_code == 404:
        return {"model_id": model_id, "error": "not found on HuggingFace"}
    if resp.status_code != 200:
        return {"model_id": model_id, "error": f"api returned {resp.status_code}"}

    try:
        data = resp.json()
    except ValueError as e:
        return {"model_id": model_id, "error": f"json parse failed: {e}"}

    card = data.get("cardData") or {}
    tags = data.get("tags") or []

    out = {
        "model_id": model_id,
        "url": f"https://huggingface.co/{model_id}",
        "author": data.get("author") or model_id.split("/")[0],
        "pipeline_tag": data.get("pipeline_tag"),
        "library_name": data.get("library_name"),
        "downloads": data.get("downloads"),
        "likes": data.get("likes"),
        "created_at": data.get("createdAt"),
        "last_modified": data.get("lastModified"),
        "private": data.get("private", False),
        "gated": data.get("gated", False),
        "tags": tags,
        "license": card.get("license") or _license_from_tags(tags),
        "languages": card.get("language") if isinstance(card.get("language"), list) else (
            [card["language"]] if card.get("language") else []
        ),
        "datasets": card.get("datasets") or [],
        "base_models": card.get("base_model") if isinstance(card.get("base_model"), list) else (
            [card["base_model"]] if card.get("base_model") else []
        ),
    }

    if include_readme:
        try:
            r = requests.get(README_URL_FMT.format(model_id=model_id), timeout=timeout, headers=headers)
            if r.status_code == 200:
                out["readme"] = r.text
            else:
                out["readme"] = None
        except requests.RequestException:
            out["readme"] = None

    return out


def _license_from_tags(tags: list) -> Optional[str]:
    for t in tags:
        if isinstance(t, str) and t.startswith("license:"):
            return t.split(":", 1)[1]
    return None


def main(argv: Optional[list] = None) -> int:
    argv = argv if argv is not None else sys.argv
    if len(argv) < 2:
        print("Usage: python -m supersearch.scrapers.huggingface_model <model_id_or_url>")
        return 1
    result = fetch(argv[1])
    print(json.dumps(result, indent=2))
    return 0 if "error" not in result else 2


if __name__ == "__main__":
    sys.exit(main())
