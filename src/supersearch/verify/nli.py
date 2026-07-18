"""NLI verification against local Ollama (qwen3:14b by default).

For each (claim, snippet) pair we ask the model to emit exactly one of
``ENTAIL`` / ``CONTRADICT`` / ``NEUTRAL``. Temperature is 0 and qwen3's
thinking mode is suppressed via the Ollama ``think: false`` request flag —
without it, a 16-token budget was being consumed by internal thinking traces
and the visible content came back empty.

Aggregation rules (``aggregate``) mirror the demo contract:
- All NEUTRAL → UNVERIFIED
- ENTAIL dominant (≥60% of non-NEUTRAL) → SUPPORTED
- CONTRADICT dominant → CONTRADICTED
- Neither side dominant → CONFLICTING

Disk cache keeps warm-run latency under the 30s demo target.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import requests

logger = logging.getLogger(__name__)

Label = Literal["ENTAIL", "CONTRADICT", "NEUTRAL"]
_VALID: tuple[Label, ...] = ("ENTAIL", "CONTRADICT", "NEUTRAL")
NLIStatus = Literal[
    "ok",
    "cached",
    "empty_evidence",
    "model_unavailable",
    "model_missing",
    "invalid_response",
]


@dataclass(frozen=True)
class ClassificationResult:
    """One semantic classification plus independent evaluator status."""

    label: Label
    status: NLIStatus
    model: str


DEFAULT_MODEL = "qwen3:14b"
DEFAULT_OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
DEFAULT_TIMEOUT = 120.0

SYSTEM_PROMPT = (
    "You are a strict textual-entailment classifier. Given a CLAIM and a SOURCE "
    "snippet, output exactly one token:\n"
    "  ENTAIL      — the source asserts the claim is true.\n"
    "  CONTRADICT  — the source asserts the claim is false.\n"
    "  NEUTRAL     — the source is irrelevant, off-topic, or does not take a position.\n"
    "No punctuation. No reasoning. No prose. Just the single token."
)

_TOKEN_RE = re.compile(r"^(ENTAIL|CONTRADICT|NEUTRAL)$", re.IGNORECASE)


# --- cache --------------------------------------------------------------------


def _cache_dir() -> Path:
    base = Path(
        os.environ.get(
            "CLAIM_VERIFIER_CACHE", Path.home() / ".cache" / "supersearch-verify"
        )
    )
    d = base / "nli"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_key(
    claim: str, snippet: str, model: str, content_hash: str | None = None
) -> str:
    h = hashlib.sha256()
    h.update(claim.encode("utf-8"))
    h.update(b"\x00")
    h.update(snippet.encode("utf-8"))
    h.update(b"\x00")
    h.update(model.encode("utf-8"))
    if content_hash:
        # v0.9: --deep passes a sha1 of the fetched page so cached entries
        # invalidate automatically when the page changes.
        h.update(b"\x00")
        h.update(content_hash.encode("utf-8"))
    return h.hexdigest()


def _cache_get(key: str) -> Label | None:
    p = _cache_dir() / f"{key}.json"
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text())
        label = data.get("label")
        if label in _VALID:
            return label  # type: ignore[return-value]
    except (OSError, json.JSONDecodeError):
        return None
    return None


def _cache_put(key: str, label: Label) -> None:
    p = _cache_dir() / f"{key}.json"
    try:
        p.write_text(json.dumps({"label": label}))
    except OSError as e:
        logger.warning("nli cache write failed: %s", e)


# --- parsing ------------------------------------------------------------------


def _parse_label(text: str) -> Label:
    """Accept one exact token only; malformed model prose is neutral."""
    if not text:
        return "NEUTRAL"
    m = _TOKEN_RE.fullmatch(text.strip())
    if m:
        return m.group(1).upper()  # type: ignore[return-value]
    return "NEUTRAL"


def _is_valid_response(text: str) -> bool:
    return _TOKEN_RE.fullmatch((text or "").strip()) is not None


# --- ollama call --------------------------------------------------------------


def _ollama_classify(
    claim: str,
    snippet: str,
    model: str,
    ollama_url: str,
    timeout: float,
) -> Label:
    """Compatibility wrapper returning only the semantic label."""
    return _ollama_classify_result(claim, snippet, model, ollama_url, timeout).label


def _ollama_classify_result(
    claim: str,
    snippet: str,
    model: str,
    ollama_url: str,
    timeout: float,
) -> ClassificationResult:
    user = f"CLAIM: {claim}\n\nSOURCE: {snippet}"
    try:
        resp = requests.post(
            f"{ollama_url}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "think": False,  # Ollama flag: disable qwen3 thinking mode
                "options": {"temperature": 0, "num_predict": 8},
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning("nli: ollama call failed (%s); evaluator unavailable", e)
        return ClassificationResult("NEUTRAL", "model_unavailable", model)
    if not isinstance(data, dict):
        return ClassificationResult("NEUTRAL", "invalid_response", model)
    message = data.get("message")
    if not isinstance(message, dict):
        return ClassificationResult("NEUTRAL", "invalid_response", model)
    content = message.get("content", "") or ""
    if not _is_valid_response(content):
        logger.warning("nli: model returned a non-token response; treating as invalid")
        return ClassificationResult("NEUTRAL", "invalid_response", model)
    return ClassificationResult(_parse_label(content), "ok", model)


def probe_model(
    model: str = DEFAULT_MODEL,
    ollama_url: str = DEFAULT_OLLAMA_URL,
    timeout: float = 2.0,
) -> NLIStatus:
    """Confirm the configured local evaluator is reachable and installed.

    Verify uses this once before consulting its NLI cache. A stale positive
    cache entry can therefore never stand in for an unavailable evaluator.
    """
    try:
        resp = requests.get(f"{ollama_url}/api/tags", timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning("nli: model probe failed (%s)", e)
        return "model_unavailable"
    if not isinstance(data, dict):
        return "model_unavailable"
    names = {
        item.get("name") or item.get("model")
        for item in data.get("models", [])
        if isinstance(item, dict)
    }
    return "ok" if model in names else "model_missing"


# --- public API ---------------------------------------------------------------


def classify(
    claim: str,
    snippet: str,
    model: str = DEFAULT_MODEL,
    ollama_url: str = DEFAULT_OLLAMA_URL,
    timeout: float = DEFAULT_TIMEOUT,
    use_cache: bool = True,
    content_hash: str | None = None,
) -> Label:
    """Classify (claim, snippet) → one of ENTAIL/CONTRADICT/NEUTRAL.

    ``content_hash`` — when set (v0.9 --deep path), it participates in the cache
    key so entries tied to a specific fetched-page version invalidate when the
    page changes. Snippet-only callers omit it; cache keys stay identical to
    v0.8 for backwards-compat.
    """
    return classify_result(
        claim,
        snippet,
        model=model,
        ollama_url=ollama_url,
        timeout=timeout,
        use_cache=use_cache,
        content_hash=content_hash,
    ).label


def classify_result(
    claim: str,
    snippet: str,
    model: str = DEFAULT_MODEL,
    ollama_url: str = DEFAULT_OLLAMA_URL,
    timeout: float = DEFAULT_TIMEOUT,
    use_cache: bool = True,
    content_hash: str | None = None,
) -> ClassificationResult:
    """Classify evidence while retaining evaluator availability separately."""
    if not snippet or not snippet.strip():
        return ClassificationResult("NEUTRAL", "empty_evidence", model)
    key = _cache_key(claim, snippet, model, content_hash=content_hash)
    if use_cache:
        hit = _cache_get(key)
        if hit is not None:
            return ClassificationResult(hit, "cached", model)
    result = _ollama_classify_result(claim, snippet, model, ollama_url, timeout)
    if use_cache and result.status == "ok":
        _cache_put(key, result.label)
    return result


def classify_batch_results(
    claim: str,
    snippets: list[str],
    model: str = DEFAULT_MODEL,
    ollama_url: str = DEFAULT_OLLAMA_URL,
    timeout: float = DEFAULT_TIMEOUT,
    use_cache: bool = True,
    content_hashes: list[str | None] | None = None,
) -> list[ClassificationResult]:
    """Status-bearing batch API used by the truthful Verify receipt."""
    hashes = (
        list(content_hashes) if content_hashes is not None else [None] * len(snippets)
    )
    if len(hashes) != len(snippets):
        raise ValueError("content_hashes length must match snippets length")
    probe = probe_model(model=model, ollama_url=ollama_url, timeout=min(timeout, 2.0))
    if probe != "ok":
        return [ClassificationResult("NEUTRAL", probe, model) for _ in snippets]
    return [
        classify_result(
            claim,
            snippet,
            model=model,
            ollama_url=ollama_url,
            timeout=timeout,
            use_cache=use_cache,
            content_hash=content_hash,
        )
        for snippet, content_hash in zip(snippets, hashes, strict=True)
    ]


def classify_batch(
    claim: str,
    snippets: list[str],
    model: str = DEFAULT_MODEL,
    ollama_url: str = DEFAULT_OLLAMA_URL,
    timeout: float = DEFAULT_TIMEOUT,
    use_cache: bool = True,
    content_hashes: list[str | None] | None = None,
) -> list[Label]:
    """Classify many snippets. Independent calls — no batching at the wire level
    (qwen3:14b is sequential on one GPU anyway), but disk cache keeps reruns fast.

    ``content_hashes`` (v0.9 --deep): optional per-snippet sha1 of the underlying
    fetched page. When provided, length must match ``snippets``. Each entry is
    forwarded to ``classify`` so deep-fetched snippets get their own cache keys.
    """
    hashes: list[str | None] = (
        list(content_hashes) if content_hashes is not None else [None] * len(snippets)
    )
    if len(hashes) != len(snippets):
        raise ValueError("content_hashes length must match snippets length")
    return [
        classify(
            claim,
            s,
            model=model,
            ollama_url=ollama_url,
            timeout=timeout,
            use_cache=use_cache,
            content_hash=h,
        )
        for s, h in zip(snippets, hashes, strict=True)
    ]


# --- aggregation --------------------------------------------------------------

DOMINANT_THRESHOLD = 0.60  # ≥60% of non-NEUTRAL → that side wins
CONFLICT_MIN_SHARE = 0.20  # if minority side ≥20% of non-NEUTRAL → CONFLICTING


def aggregate(labels: list[Label]) -> str:
    """Return the top-level verdict string per the demo contract."""
    if not labels:
        return "UNVERIFIED"
    entail = sum(1 for lbl in labels if lbl == "ENTAIL")
    contra = sum(1 for lbl in labels if lbl == "CONTRADICT")
    non_neutral = entail + contra
    if non_neutral == 0:
        return "UNVERIFIED"
    e_share = entail / non_neutral
    c_share = contra / non_neutral
    if e_share >= DOMINANT_THRESHOLD and c_share < CONFLICT_MIN_SHARE:
        return "SUPPORTED"
    if c_share >= DOMINANT_THRESHOLD and e_share < CONFLICT_MIN_SHARE:
        return "CONTRADICTED"
    return "CONFLICTING"
