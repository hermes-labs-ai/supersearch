# Product V1 evaluation outcome

The historical evaluation supported a standalone retrieval package centered on
deadline-bounded heterogeneous search fan-out. The distribution is
`hermes-supersearch`; its Python import and CLI are `supersearch`. Verify is an
optional source-bound evidence workflow.

The final evaluation recorded 27 parallel results over three queries, of which
15 met the preregistered usefulness criteria. Each query had a useful first
result. These measurements cover one bounded pack, not general search quality.
See [the benchmark](results/BENCHMARK.md), [human labels](results/HUMAN-EVALUATION.md),
and [machine receipt](results/PRODUCT-RECEIPT.json) for the exact evidence.

The generic CLI and a reported Claude Code trial used the same JSON protocol.
The Codex network-enabled summary failed its schema and is not a protocol PASS;
a separate sandbox trial reported source unavailability honestly. The raw
agent-host logs are not public, so these host outcomes are reported observations.

Reproducible regressions to check include an install that cannot emit parseable
JSON, a failed source mislabeled as successful, or a slow source extending the
parallel deadline. Product APIs, deterministic controls, query receipts, and
limitations remain available for independent evaluation.

This document summarizes historical product evidence. It is not an instruction
to publish or a promise about future product direction.
