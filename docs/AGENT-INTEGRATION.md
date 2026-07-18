# Agent integration

SuperSearch uses a framework-neutral CLI/JSON and Python boundary. Product V1
does not add LangChain, CrewAI, or MCP wrappers because they would duplicate a
contract those hosts can already call.

## CLI contract

```bash
supersearch search "<literal query>" \
  --sources ddg,hn,github,arxiv \
  --deadline 12
```

- stdout: exactly one `supersearch.search.v1` JSON document;
- stderr: source diagnostics and CLI errors;
- exit `0`: completed receipt, including `ok`, `partial`, or `no_results`;
- exit `2`: invalid request;
- exit `3`: retrieval unavailable and no result;
- no progress text or Markdown is mixed into stdout.

Agents should branch on `status` and each item in `sources` before using
`results`. A `partial` receipt is not an error to hide: pass its missing-source
state into downstream reasoning.

## Minimal host prompt

```text
Run this command exactly and parse its JSON stdout:

supersearch search "RFC 9116 security.txt well-known path" --deadline 12

Report one relevant URL and all sources marked failed or timed_out. Treat the
output as source discovery, not an answer or factual certification.
```

## Python contract

```python
from supersearch import fanout_search

receipt = fanout_search("query", deadline_seconds=12)
if receipt["status"] == "unavailable":
    raise RuntimeError(receipt["sources"])
```

The public dictionary is JSON-serializable. Lower-level `SearchResult` objects
remain available to Python callers that need extension hooks.

## Re-entry and failure

The command is stateless except for the DDGS query cache. If a host is
interrupted, rerun the same command. A second run can differ because indexes,
network availability, and caching change; preserve `retrieved_at` and the full
receipt when reproducibility matters.

Do not automatically retry a `failed` source indefinitely. Prefer one bounded
retry or continue with an explicitly partial receipt.

