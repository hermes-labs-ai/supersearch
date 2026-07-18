# SuperSearch Product V1 evaluation preregistration

Frozen before Product V1 implementation or live evaluation on **2026-07-18**.

## Product claim under test

SuperSearch should be useful as a local, agent-native search fan-out: one query is
sent concurrently to heterogeneous public web, code, community, and research
surfaces; one overall deadline contains slow sources; the default path needs no
paid API key and no LLM; and the output preserves result provenance plus honest
source availability.

This evaluation does **not** test general search quality or factual truth. It is
a small workflow evaluation of the named queries, sources, machine, and network
conditions recorded in the resulting receipt.

## Fixed live query pack

All three hosts (direct CLI, Codex, and Claude/Fable) receive the same query IDs
and text. They may explain the receipt, but they must not rewrite the query.

| ID | Recurring job | Query | Useful-result criterion |
|---|---|---|---|
| `Q1` | migration scouting | `Python 3.12 distutils removal migration setuptools` | A result gives concrete migration guidance or an authoritative removal notice. |
| `Q2` | open-source landscape | `SQLite vector search extension sqlite-vec USearch` | A result identifies a relevant implementation, documentation page, or substantive comparison. |
| `Q3` | standard lookup | `RFC 9116 security.txt well-known path` | A result gives the standard, an implementation, or technically relevant discussion. |

## Fixed live configuration

- Sources: `ddg,hn,github,arxiv`
- Maximum results per source: `3`
- Overall deadline: `12` seconds
- Cache: source defaults; DDGS-backed searches may use SuperSearch's local
  24-hour query cache, while the three direct sources are not cached by the
  orchestrator. The benchmark records this limitation.
- Reranking: off
- LLM: none in the SuperSearch process
- Paid API keys: none supplied by the evaluation harness

## Measures

For every query:

1. wall-clock duration;
2. unique result URLs and domains;
3. source completion, failure, and timeout states;
4. provenance breadth (distinct source identities represented in results);
5. human-readable useful-result count under the fixed criterion above;
6. output parseability and whether failure states are explicit.

Parallel versus serial timing is run on the same query/configuration. Because
the public network can change between calls and caching can affect DDGS, timing
is descriptive, not a general performance estimate.

## Deterministic controls

The product tests must demonstrate independently of the live network that:

- two equally slow sources complete materially faster in parallel than serial;
- a source hanging beyond the overall deadline does not block a fast sibling;
- a source exception produces an explicit failed source state;
- an empty but successful source is distinct from a failed source;
- duplicate URLs preserve all source identities;
- stdout from the agent CLI is exactly one parseable JSON document;
- the default path does not instantiate an LLM or local reranker.

## Cross-agent protocol

Each host is asked to:

1. run the documented clean-install command in its isolated checkout/venv;
2. invoke the stable JSON CLI for the fixed query;
3. parse the receipt;
4. report one useful result and any failed/timed-out source without treating the
   result as an answer or certification.

Success means the host can use the same CLI/JSON contract without a bespoke
framework adapter. Host prose is evidence about integration friction only, not
evidence about result truth.

## Stop and decision rule

- Recommend a **standalone OSS Product V1 candidate** if the clean base install,
  direct CLI/Python path, deterministic controls, and at least two host trials
  work without a paid key or model, and the README states the limitations.
- Keep the Evidence Bridge as an **unpublished experimental appendix** unless a
  later exact falsifier closes its component hold.
- Hold Product V1 if the stable output launders availability, the deadline does
  not contain a hung source, clean install needs an undisclosed model/key, or
  the first-use path cannot produce a useful receipt.

