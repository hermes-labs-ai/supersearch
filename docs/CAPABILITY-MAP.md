# Capability map at the Product V1 boundary

Inspected against the sealed parent `d0e4aa30f06ae192738aad195b31b1aa5094c467`
and the Evidence Component terminal head `2dd9e99cdb11cf811dccf1e501c39e4257654d84`
on 2026-07-18.

## Core candidate

| Surface | Code evidence | Product disposition |
|---|---|---|
| heterogeneous source fan-out | `sources.search_all` and source classes | Core |
| daemon-thread parallelism with one monotonic deadline | `sources.search_all` | Core |
| URL deduplication and source identity stitching | `sources._merge_with_provenance` | Core |
| DDGS metasearch plus HN, GitHub, arXiv, and other direct surfaces | `search.py`, `sources.py`, `sources_ext/` | Core, with source-specific availability caveats |
| Python result objects | `search.SearchResult` | Core but too low-level as the only public contract |
| diagnostics capture | `diagnostics.py`, optional argument to `search_all` | Core mechanism; Product V1 must expose structured status |

The current `search_all` default path has `rerank=False`. It makes network
requests but does not call an LLM, local or hosted. No paid key is required for
the default four sources; an optional GitHub token can increase GitHub API rate
limits.

## Optional

| Surface | Dependency/behavior | Disposition |
|---|---|---|
| local reranking | Ollama embeddings via `LocalReranker`; model calls are not bounded by the Product V1 total deadline | Experimental legacy capability; rejected by `fanout_search` and absent from the Product V1 CLI |
| page fetching | requests + lxml, no model | Optional extraction primitive |
| Verify receipts | local Ollama evaluator for positive verdicts; fail-closed `UNVERIFIED` when unavailable | Optional evidence workflow, not truth certification |
| SearXNG | user-supplied/self-hosted instance | Optional source |
| authenticated GitHub | `GITHUB_TOKEN` when present | Optional quota improvement |

## Experimental or internal

| Surface | Reason | Product disposition |
|---|---|---|
| `research` | multi-hop/fetch/analyze workflow, local-model-oriented and destructive replacement of its selected output directory | Experimental; not in first screen |
| intelligence routing | embedding-based route selection and limited lived-workflow proof | Experimental |
| query expansion | local-model path and limited product evaluation | Experimental |
| scraper one-shots | heterogeneous maintenance and dependency quality | Experimental utilities |
| self-improvement report | maintainer utility, not user job | Internal |
| Evidence Bridge adapter | terminal component status `PHASED_COMPONENT_HOLD`; missing-member rejection remains the next falsifier | Internal experimental appendix; no integration |
| legacy positional CLI | always reranks/summarizes and mixes progress text with JSON | Compatibility-only until replaced or removed in a later major version |

## Broken or misleading pre-Product-V1 surface

The positional command `supersearch "query"` is not a truthful first-use path:
it constructs a local reranker and calls local summarization by default, its
`--local` flag does not change that default, `--summarize` emits a subagent
prompt rather than performing a hosted summary, and progress text shares stdout
with JSON. Product V1 therefore adds an explicit `supersearch search` command
instead of documenting the legacy path as core.

## Dependency truth

The current base wheel declares `ddgs`, `requests`, `numpy`, `lxml`, and `httpx`.
Only the first two are intrinsic to the narrow default fan-out; lxml supports
fetching and some bundled sources, while numpy/httpx support optional local
ranking, expansion, and summarization. Product V1 will not claim a smaller
dependency set until packaging actually separates those optional surfaces.
