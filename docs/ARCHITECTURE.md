# Product V1 architecture

## Boundary

Product V1 is a retrieval orchestrator, not a research agent. Its stable path is
the `supersearch.search.v1` receipt emitted by `supersearch search` and returned
by `supersearch.fanout_search`.

```text
                         ┌─ DDGS (web metasearch)
query + source list ─────┼─ HN Algolia (community)
                         ├─ GitHub Search (code)
                         └─ arXiv (research)
                                   │
                     daemon thread per selected source
                                   │
                    one process-local monotonic deadline
                                   │
                  deterministic URL/provenance merge
                                   │
                  source-explicit versioned receipt
```

The default source list is `ddg,hn,github,arxiv`. Other registered sources are
available explicitly and carry their own availability and policy risks.

## Deadline and isolation

`sources.search_all` starts a daemon thread per selected source and collects
results through a queue until one overall deadline expires. It does not use a
`ThreadPoolExecutor`, whose non-daemon workers can be joined during interpreter
shutdown. A source that misses the deadline is omitted and marked `timed_out`;
threads cannot be safely killed in Python, so its in-flight socket may continue
until its own request timeout while the process continues.

This is isolation from caller latency, not cancellation of remote work.
The hidden serial mode exists for controlled comparison and explicitly marks
`deadline_enforced: false`; it is not the documented agent path.

For the CLI, once the complete JSON receipt and stderr diagnostics are flushed,
the command uses an immediate process exit. This prevents third-party client
cleanup hooks from extending the caller-visible deadline after a source has
already been marked `timed_out`. The Python API returns at the deadline but
keeps its host process alive; an abandoned adapter thread can continue until
its underlying request timeout.

## Determinism

The network and indexes are not deterministic. The orchestrator is deterministic
about the following local mechanics:

- requested source order, regardless of thread completion order;
- first-seen URL ordering within that source order;
- URL deduplication;
- ordered union of source identities for duplicate URLs;
- explicit state taxonomy: `completed`, `degraded`, `failed`, `timed_out`;
- one versioned JSON shape.

## Result and source provenance

Each merged result carries `sources`, the selected source adapters that returned
that URL in this call. This is retrieval-route provenance. It is not a claim
that an adapter authored the page, that sources are independent, or that the
snippet is a literal page excerpt.

The receipt also carries one status object per requested source. A source that
returned no matches without diagnostics is `completed` with `result_count: 0`.
A caught network/parser diagnostic and no results is `failed`. Results plus a
diagnostic are `degraded`. Missing the total deadline is `timed_out`.

## Models

The default path calls `search_all(..., rerank=False)` and invokes no model.
The deadline-bounded CLI and `fanout_search` reject reranking because the local
Ollama embedding calls are not yet governed by the receipt's total deadline.
`LocalReranker` and legacy `search_all(..., rerank=True)` remain experimental
package capabilities, not Product V1 surfaces. Verify is a separate optional
workflow with fail-closed evaluator semantics.

## Cache

The DDGS wrapper uses a local JSON query cache with a 24-hour TTL by default.
Direct source adapters in the fan-out are not cached by the orchestrator. The
Product V1 receipt exposes that policy, but it does not yet expose per-result
cache-hit state. A future cache API must preserve source and retrieval-time
identity before it can become core.

## Trust boundary

Search responses, HTML, snippets, titles, and fetched pages are untrusted input.
The core path does not execute returned content. Agents consuming results must
treat text as data, validate URLs before privileged fetching, and preserve the
receipt rather than converting a snippet into a fact.
