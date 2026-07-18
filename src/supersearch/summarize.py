"""
summarize.py — Scaffolded Haiku summarization for SuperSearch results.

Scaffold design based on TierJump research (PF-001 through PF-007):
- "Guards not curricula" — negative constraints, not teaching
- One constraint block at top, not per-result
- Contrastive markers for quality anchoring
- Prefix injection for structured output
"""


import httpx

# Proven scaffold from TierJump research
# Combined Guard Constraints + QuickThink scaffold
# Winner of A/B test across 5 scaffold variants (2026-03-21)
# Guard constraints prevent hallucination, QuickThink adds analytical depth
# calibrated: intentional multi-technique (contrastive guards + format + step-by-step);
# subadditive stacking is accepted — each technique addresses a distinct failure mode
# (hallucination, structure, synthesis). Measured via blind eval 2026-03-21.
SEARCH_SUMMARY_SCAFFOLD = """## CONSTRAINTS (mandatory)
- Answer ONLY from the search results provided below. NOT from general knowledge.
- Cite which result (by number) supports each claim. NOT vague references.
- If the results don't contain enough info, say what's missing. NOT fill gaps with assumptions.
- This is SYNTHESIS. NOT copy-paste. Connect findings across results into a coherent answer.
- If results contradict each other, note the contradiction. NOT pick one silently.
- Be specific: include numbers, names, URLs when available. NOT "some sources say."

## BEFORE ANSWERING
Write a brief compressed plan: g:[goal];c:[constraints from results];s:[key findings to connect];r:[risks: gaps, contradictions, hallucination potential]

## FORMAT
Then answer the query in 2-4 paragraphs. After the answer, list sources as:
[1] Title — URL
[2] Title — URL
..."""

# Prefix injection to start the structured output
ANSWER_PREFIX = "Based on the search results:\n\n"


def build_prompt(query: str, results: list[dict]) -> tuple[str, str]:
    """Build the system + user prompt for summarization."""
    
    # Format results for the model
    results_text = ""
    for i, r in enumerate(results, 1):
        results_text += f"[{i}] {r.get('title', 'Untitled')}\n"
        results_text += f"    URL: {r.get('url', r.get('href', ''))}\n"
        results_text += f"    {r.get('snippet', r.get('body', ''))}\n\n"
    
    system = SEARCH_SUMMARY_SCAFFOLD
    user = f"Query: {query}\n\nSearch Results:\n{results_text}\nSynthesize an answer to the query from these results."
    
    return system, user


EXTRACTION_SCAFFOLD = """## TASK
Extract structured data from this web page. Return ONLY the facts found on the page.

## CONSTRAINTS
- Extract ONLY what is explicitly stated on the page. NOT from your general knowledge.
- If a data point is not on the page, write "not found" for that field.
- Be specific: exact numbers, exact names, exact prices. NOT approximations.

## FIELDS TO EXTRACT
- Company/Product name
- What it does (one sentence)
- Pricing (exact tiers and amounts if available)
- Funding (amount, round, date if available)
- Key stats (users, GitHub stars, benchmarks, performance numbers)
- Key features (bullet list)
- Limitations or weaknesses mentioned
- Any other notable facts

## FORMAT
Return as a structured block. No prose. Just the fields and values."""


def extract_with_ollama(
    query: str,
    title: str,
    url: str,
    page_text: str,
    model: str = "qwen3:14b",
    ollama_url: str = "http://localhost:11434",
) -> dict | None:
    """Extract structured data from a fetched page using local model. Zero API cost."""

    user = f"Query context: {query}\nPage: {title} ({url})\n\nPage content:\n{page_text[:4000]}"

    with httpx.Client(timeout=180.0) as client:
        resp = client.post(
            f"{ollama_url}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": EXTRACTION_SCAFFOLD},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "options": {"temperature": 0, "num_predict": 2048},
            },
        )

        if resp.status_code != 200:
            return None

        data = resp.json()
        extraction = data.get("message", {}).get("content", "")

        return {
            "title": title,
            "url": url,
            "extraction": extraction,
            "model": model,
            "cost": "$0.00 (local)",
        }


def summarize_with_haiku_subagent(
    query: str,
    results: list[dict],
) -> dict:
    """
    Summarize via OpenClaw subagent (uses OpenClaw's auth, no separate API key).
    Call this from within an OpenClaw agent session.
    Returns the scaffold + prompt for the subagent to use.
    """
    system, user = build_prompt(query, results)
    
    # Return the prompt for the caller to pass to sessions_spawn
    return {
        "task": f"{system}\n\n{user}\n\nStart your answer with: {ANSWER_PREFIX}",
        "model": "anthropic/claude-haiku-4-5",
        "scaffold": "tierjump-guard-quickthink-v1",
    }


def summarize_with_ollama(
    query: str,
    results: list[dict],
    model: str = "qwen3:14b",
    ollama_url: str = "http://localhost:11434",
) -> dict:
    """Summarize search results using a local Ollama model (free, zero API cost)."""
    
    system, user = build_prompt(query, results)
    
    with httpx.Client(timeout=180.0) as client:
        resp = client.post(
            f"{ollama_url}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                    {"role": "assistant", "content": ANSWER_PREFIX},
                ],
                "stream": False,
                "options": {"temperature": 0, "num_predict": 2048},
            },
        )
        
        if resp.status_code != 200:
            return {"error": f"Ollama error {resp.status_code}"}
        
        data = resp.json()
        answer = ANSWER_PREFIX + data.get("message", {}).get("content", "")
        
        return {
            "query": query,
            "answer": answer,
            "model": model,
            "scaffold": "tierjump-research-v1",
            "cost": "$0.00 (local)",
        }
