# Product V1 evaluation

This directory contains the historical 0.11.0 evaluation: fixed queries and
criteria, machine measurements, human usefulness labels, host integration
reports, and deterministic controls. It does not establish general search
quality, factual truth, or vendor superiority.

- `PREREGISTRATION.*`: the original evaluation design, with explicitly recorded
  public redactions. Query text, criteria, configuration, and controls are unchanged.
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

## Public copy provenance

The 2026-09-24 cleanup removed operating metadata and normalized local command
paths and host labels. JSON redaction notes identify original public content by
hash; Git history retains the earlier versions. The raw final query receipts,
human labels, live summary, and deadline-control result are unchanged. Hashes in
`PRODUCT-RECEIPT.json` identify the current public copies. No evaluation was rerun
or new performance claim introduced by that cleanup.
