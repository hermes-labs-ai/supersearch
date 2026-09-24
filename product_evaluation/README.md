# Product V1 evaluation

This directory contains the historical 0.11.0 evaluation: fixed queries and
criteria, machine measurements, human usefulness labels, host integration
reports, and deterministic controls. It does not establish general search
quality, factual truth, or vendor superiority.

- `PREREGISTRATION.*`: fixed query text, criteria, configuration, and controls.
- `run_live_pack.py`: capture the same query pack from an installed CLI.
- `results/live-final/`: original final parallel/serial query receipts.
- `results/HUMAN-EVALUATION.*`: criterion-bound usefulness labels.
- `results/HOST-TRIALS.*`: reported host outcomes, including the schema-invalid
  network-enabled Codex summary and failure-honesty negative control.
- `results/PRODUCT-RECEIPT.json`: bounded results, hashes, and nonclaims.
- `deadline_probe.py`: reproducible slow-source and process-exit control.
- `FIVE-MINUTE-SHOWCASE.md`: demo commands and scope.

Agent-host raw logs are not public. Their hashes identify reported historical
observations, not independently inspectable public proof. The generic CLI
receipts and evaluation harnesses are public so readers can run their own trials.
Model-host trials require separately configured host tools and may incur host
model costs; SuperSearch's core search itself invokes no model.

The cross-host harness requires `python -m pip install '.[test]'` and validates
actual host stdout against `host-trial-output.schema.json`. Pass `--codex-model`
or `--claude-model` only when a particular installed host configuration requires
it; otherwise each host uses its own default. Capture output outside the source
checkout. Review and normalize logs before sharing them.

## Evidence provenance

The normalized reports retain the original evaluation inputs and measurements.
Their provenance fields identify the source documents by hash. The final query
receipts, human labels, live summary, and deadline control describe the original
0.11.0 runs. Companion hashes in `PRODUCT-RECEIPT.json` identify the current
report files; formatting and host-label normalization do not represent new runs.
