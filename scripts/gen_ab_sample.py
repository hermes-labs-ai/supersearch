#!/usr/bin/env python3
"""Regenerate ab-sample.txt with real qwen model output.

Runs one real query through both qwen2.5:1.5b (A) and qwen3:14b (B) via
summarize_with_ollama, using the SAME intelligence-routed payload for both.
Strips qwen3 think-tokens so the length ratio reflects final prose. Captures
completions verbatim and writes ab-sample.txt at the repo root.

Run whenever you want a fresh real-prose artifact (not called by pytest).
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from supersearch.summarize import summarize_with_ollama  # noqa: E402
from supersearch.sources import search_all  # noqa: E402
from supersearch.rerank import LocalReranker  # noqa: E402
from supersearch.routing import route  # noqa: E402

QUERY = "GPT-4 context window parameters"

# Use ONE intelligence-routed payload and run it through both models. The A/B
# varies only on model choice — this keeps the ratio a measure of model
# verbosity, not retrieval variance, so the SCOPE 0.3–3.0 gate is stable.
routed = route(QUERY)
raw = search_all(QUERY, sources=routed, max_per_source=3)

reranker = LocalReranker()
ranked = reranker.rerank(QUERY, raw)[:5]
payload = [{"title": r.title, "url": r.url, "snippet": r.snippet} for r, _s in ranked]

out_a = summarize_with_ollama(QUERY, payload, model="qwen2.5:1.5b")
out_b = summarize_with_ollama(QUERY, payload, model="qwen3:14b")


def _strip_think_tokens(text: str) -> str:
    """qwen3 sometimes emits <think>...</think> deliberation; strip it so the
    ratio reflects final-answer prose length, not reasoning overhead."""
    import re
    return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL)


out_a["answer"] = _strip_think_tokens(out_a["answer"])
out_b["answer"] = _strip_think_tokens(out_b["answer"])

len_a, len_b = len(out_a["answer"]), len(out_b["answer"])
ratio = len_b / len_a if len_a else 0.0

lines = [
    "# Task 3 — A/B length ratio sample (real qwen model outputs)",
    "",
    f"Query: {QUERY}",
    f"A = qwen2.5:1.5b  → {len_a} chars",
    f"B = qwen3:14b     → {len_b} chars",
    f"ratio B/A = {ratio:.3f}",
    f"GATE (0.3 <= ratio <= 3.0): {'PASS' if 0.3 <= ratio <= 3.0 else 'FAIL'}",
    "",
    f"## A — qwen2.5:1.5b (model={out_a['model']}, scaffold={out_a['scaffold']})",
    "",
    "### Shared input payload (intelligence-routed, top-5 reranked)",
    "",
    "```json",
    json.dumps(payload, indent=2),
    "```",
    "",
    "### Completion",
    "",
    out_a["answer"],
    "",
    f"## B — qwen3:14b (model={out_b['model']}, scaffold={out_b['scaffold']})",
    "",
    "### Shared input payload (same as A)",
    "",
    "```json",
    json.dumps(payload, indent=2),
    "```",
    "",
    "### Completion",
    "",
    out_b["answer"],
    "",
]
(REPO / "ab-sample.txt").write_text("\n".join(lines) + "\n")
print(f"wrote ab-sample.txt  ratio={ratio:.3f}")
