# SuperSearch

**One query across web, code, community, and research sources. One deadline.**

SuperSearch is a local Python library and CLI for agents and engineers who need
a useful source set before they can investigate, compare, or verify something.
It searches heterogeneous public surfaces concurrently, deduplicates URLs,
preserves which sources surfaced each result, and returns without letting one
slow source hold the whole call open.

The default `search` path needs **no paid search key and no LLM**. It returns
search evidence, not an answer.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install hermes-supersearch
supersearch search "Python 3.12 distutils removal migration setuptools" --pretty
```

The PyPI distribution is `hermes-supersearch`; the Python import and CLI command
are both `supersearch`.

The command writes exactly one versioned JSON document to stdout:

```json
{
  "schema_version": "supersearch.search.v1",
  "status": "partial",
  "sources": [
    {"name": "ddg", "status": "completed", "result_count": 3, "diagnostics": []},
    {"name": "github", "status": "failed", "result_count": 0, "diagnostics": ["..."]}
  ],
  "results": [
    {
      "rank": 1,
      "title": "...",
      "url": "https://...",
      "snippet": "...",
      "sources": ["ddg", "hn"],
      "score": null
    }
  ]
}
```

`partial` is a usable result with at least one degraded, failed, or timed-out
source. `unavailable` means source failures prevented any result. A completed
source with zero matches is reported separately from a failed source.

## The recurring job

Use SuperSearch when an agent or engineer needs to scout several kinds of
public evidence under a bounded latency budget:

- find migration guidance across web docs, GitHub, and practitioner discussion;
- map an unfamiliar open-source landscape without searching each surface by hand;
- collect standards, implementations, and community context before analysis;
- feed source URLs and snippets into an agent through a framework-neutral JSON
  or Python contract.

If one web index is sufficient, call that index directly. If you need a hosted
answer engine, managed crawling, an SLA, or a comprehensive research report,
use a service built for that job. SuperSearch is the local fan-out layer between
those two cases.

## Five-minute quickstart

List the registered surfaces:

```bash
supersearch search --list-sources
```

Choose a source mix and total deadline:

```bash
supersearch search \
  "SQLite vector search extension sqlite-vec USearch" \
  --sources ddg,hn,github,arxiv \
  --max-per-source 3 \
  --deadline 12 \
  --pretty > receipt.json
```

Inspect availability before consuming results:

```bash
python - <<'PY'
import json

receipt = json.load(open("receipt.json"))
print(receipt["status"])
for source in receipt["sources"]:
    print(source["name"], source["status"], source["result_count"])
for result in receipt["results"][:3]:
    print(result["sources"], result["title"], result["url"])
PY
```

The [five-minute showcase](product_evaluation/FIVE-MINUTE-SHOWCASE.md) uses the
same path and calls out what every field does and does not mean.

## Python API

```python
from supersearch import fanout_search

receipt = fanout_search(
    "RFC 9116 security.txt well-known path",
    sources=["ddg", "hn", "github", "arxiv"],
    max_per_source=3,
    deadline_seconds=12,
)

if receipt["status"] in {"ok", "partial"}:
    for result in receipt["results"]:
        print(result["sources"], result["url"])
```

The JSON contract is documented in
[`docs/search-receipt-v1.schema.json`](docs/search-receipt-v1.schema.json).
Existing low-level callers can still use `supersearch.sources.search_all` and
`SearchResult` directly.

## Architecture

```text
query
  ├─ DDGS metasearch ───────────────┐
  ├─ Hacker News API ───────────────┤
  ├─ GitHub Search API ─────────────┼─ one monotonic deadline
  └─ arXiv API ─────────────────────┘
                                      ↓
                         URL dedupe + provenance merge
                                      ↓
                     supersearch.search.v1 JSON receipt
```

Each source runs on a daemon thread. The caller waits on one monotonic total
deadline, not the sum of per-source timeouts. A late source is abandoned for
that call; fast siblings still return. Output order is re-keyed to the requested
source order before merging, so thread completion order does not reorder the
receipt.

DDGS itself can query several web backends. SuperSearch adds direct code,
community, academic, regulatory, and company surfaces around that web layer.
See [architecture](docs/ARCHITECTURE.md) and the inspected
[capability map](docs/CAPABILITY-MAP.md).

## Core, optional, and experimental

| Tier | Surface | Model/key requirement |
|---|---|---|
| Core | `supersearch search`, `fanout_search`, deadline fan-out, dedupe, provenance, source status | No LLM; no paid key for defaults |
| Experimental | legacy `LocalReranker` / `search_all(..., rerank=True)` | Local Ollama embedding model requested; outside the Product V1 total-deadline contract |
| Optional | `supersearch verify` source-bound evidence receipt | Local Ollama evaluator for positive verdicts; otherwise fail-closed `UNVERIFIED` |
| Optional | authenticated GitHub and self-hosted SearXNG sources | User-supplied credential or service |
| Experimental | `research`, intelligence routing, query expansion, scraper utilities | Mixed; some paths use local models |
| Internal | Research Evidence Bridge shadow adapter | Component hold; not integrated or published |

The older positional command `supersearch "query"` remains for compatibility,
but it reranks and summarizes through local-model-oriented code and is not the
Product V1 entry point.

## What it refuses to claim

SuperSearch does not claim that:

- a result, snippet, or `SUPPORTED` Verify verdict is true or certified;
- its indexes are broader, fresher, faster, or more relevant than hosted APIs;
- every public source permits unlimited automated use or will remain available;
- a completed search is exhaustive;
- source provenance proves authorship, independence, or authority;
- the default cache is a freshness guarantee.

Verify verdicts describe a relationship between a claim and named retrieved
evidence. They are not general truth judgments. Read the
[Verify receipt contract](docs/verify-receipt-v1.md).

## Network, privacy, freshness, and cost

Queries leave the machine and are sent to the selected public services. Those
services can log, rate-limit, personalize, or block requests under their own
terms. SuperSearch has no telemetry service and requires no SuperSearch account.
Do not send secrets or private claims to public sources.

The default path has no SuperSearch per-query fee and requires no paid API key,
but it still uses your network and compute. Optional services, credentials, or
local models have their own costs. DDGS-backed queries may be served from a
local JSON cache for up to 24 hours; direct fan-out sources are not cached by
the orchestrator. Details: [privacy and cost](docs/PRIVACY-COST.md).
Set `SUPERSEARCH_CACHE_DIR` when a sandbox must keep cache writes in a specific
root.

## Alternatives

SuperSearch is not a replacement for every search product:

| Need | Better fit |
|---|---|
| direct free web metasearch with its own CLI/MCP | DDGS |
| a broad, operator-controlled metasearch service | SearXNG |
| managed search/extraction with accounts, quotas, and vendor infrastructure | Tavily, Exa, or Firecrawl |
| local heterogeneous fan-out with one total deadline and source-state receipts | SuperSearch |

The source-bound [comparison notes](docs/MARKET-NOTES.md) record official links,
retrieval date, and dimensions. They make no cross-product ranking-quality or
truth-accuracy claim.

## Installation and distribution truth

SuperSearch supports Python 3.10+ and currently declares `ddgs`,
`requests`, `numpy`, `lxml`, and `httpx`. Numpy and httpx mostly serve optional
local-model paths; they remain base dependencies, so the
README does not pretend the wheel is slimmer than it is.

PyPI already has a case-insensitive `Super-Search` distribution. The public
distribution is therefore `hermes-supersearch`, while the import, CLI command,
and public repository remain `supersearch`.

## Tests

```bash
python -m pip install -e '.[test]'
python -m pytest
```

Offline tests cover result merging, deterministic parallel/serial equivalence,
deadline containment, source-status honesty, JSON parseability, Verify receipt
semantics, and optional workflows. Live model tests remain opt-in.

## Project documents

- [Agent integration](docs/AGENT-INTEGRATION.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Distribution plan](docs/DISTRIBUTION.md)
- [Limitations](docs/LIMITATIONS.md)
- [Privacy, network, and cost](docs/PRIVACY-COST.md)
- [Roadmap](docs/ROADMAP.md)
- [Product evaluation](product_evaluation/README.md)
- [Contributing](CONTRIBUTING.md), [security](SECURITY.md), and [Apache-2.0 license](LICENSE)
