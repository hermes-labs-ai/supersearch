# Bounded Product V1 benchmark

Final live pack wheel:
`746bcf6a0cb6de7c3f04d681246406b05db125e568c347198a62534ae8d41192`
(`hermes-supersearch` 0.11.0, Python 3.13.12). The harness removed
`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GITHUB_TOKEN`, `TAVILY_API_KEY`,
`EXA_API_KEY`, and `FIRECRAWL_API_KEY` from every SuperSearch subprocess and
requested no reranker or model.

| Query | Parallel status/results/domains | Parallel wall | Serial status/results | Serial wall | Observed reduction |
|---|---|---:|---|---:|---:|
| Q1 | ok / 6 / 3 | 8.668 s | ok / 6 | 22.590 s | 61.6% |
| Q2 | ok / 12 / 5 | 12.341 s | partial / 9 | 14.095 s | 12.4% |
| Q3 | ok / 9 / 4 | 2.509 s | ok / 9 | 16.273 s | 84.6% |

The three parallel calls totaled 23.519 seconds versus 52.959 seconds serial.
This sum is descriptive only. Q2 is not an equal-completion comparison because
arXiv failed during its serial call, and network/cache conditions changed
between calls.

## Slow-source containment and repair

The initial pack found a material process-tail defect: Q2's receipt returned at
12.006 seconds with DDGS marked `timed_out` and nine sibling results, but the CLI
process took 15.284 seconds to exit. Product commit `eb68f56` repaired the CLI
boundary. The deterministic process control registers a 30-second atexit hook in
a timed-out source; the repaired CLI returned a `partial` one-result receipt in
252.609 ms and the process exited in 576.795 ms under a 250 ms deadline. Control
status: PASS (`DEADLINE-CONTROL.json`, SHA-256
`a1a784e29034372948e802b8eb402ad1ce86bf5cd395504c367bb30150a9eb3f`).

## Value and failure honesty

- 27 final parallel results across 3–5 domains per query;
- 15/27 met the preregistered useful-result criteria;
- every query had a useful rank-1 result;
- initial and host trials exercised `failed`, `timed_out`, `partial`, and
  `unavailable` without converting them into successful search;
- direct CLI, Python API tests, Codex, and Claude/Fable all parsed the same JSON
  contract without a framework adapter.

## Limits

Three queries, one machine, one date, public network drift, DDGS caching, and
one human reviewer cannot establish general relevance, recall, latency, or
truth. The repeated off-topic arXiv tail shows why users should select source
mixes for the job instead of equating more sources with better results.

