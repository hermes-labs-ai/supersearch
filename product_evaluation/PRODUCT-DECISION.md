# Product V1 decision

## Decision: standalone OSS candidate

SuperSearch should ship, under separate exact publication authority, as a
standalone Product V1 centered on deadline-bounded heterogeneous search fan-out.
The public repository can be named `supersearch`; the PyPI distribution should
be `hermes-supersearch`, with the `supersearch` import and CLI retained.

Verify stays as an optional source-bound evidence workflow. The Evidence Bridge
shadow adapter stays an unpublished internal appendix with terminal status
`PHASED_COMPONENT_HOLD`; it is neither the product center nor an integration
recommendation.

## Evidence for the decision

- clean wheel install on Python 3.13.12: PASS;
- offline suite: 255 passed, 2 opt-in live-model skips at the last product run;
- final live pack: 27 parallel results, 15 criterion-useful, useful rank 1 for
  all three queries;
- final live parallel calls: 8.668 s, 12.341 s, and 2.509 s versus 22.590 s,
  14.095 s, and 16.273 s serial under changing network conditions;
- deterministic process control: 250 ms deadline, partial receipt in 253 ms,
  process exit in 577 ms despite a registered 30-second cleanup hook;
- generic CLI, Claude/Fable, and network-enabled Codex all used the same JSON
  protocol without an adapter; sandboxed Codex converted DNS denial into exact
  `unavailable` receipts;
- the README leads with the user job, one truthful install path, core/optional/
  experimental boundaries, privacy/network/cost, and nonclaims.

## Exact next action

Prepare a new public repository from the allowlisted local export, preserving
Apache-2.0 and the final source/hash receipt, then publish the
`hermes-supersearch` wheel only under separate exact authority. Do not publish
the raw internal Evidence Bridge appendix or raw host logs. No product-choice
or adapter-choice gate remains.

## Next falsifier

A fresh supported-platform install that cannot produce a parseable receipt, a
source failure that becomes `ok`, or caller-visible latency materially exceeding
the declared parallel deadline after the receipt repair should hold publication.
Ordinary ranking noise, optional dependency slimming, and framework adapters are
backlog, not reasons to reopen Product V1.
