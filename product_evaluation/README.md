# Product V1 evaluation

This directory separates preregistration, machine capture, human usefulness
labels, host-integration trials, and the final bounded evaluation receipt.

- `PREREGISTRATION.*`: frozen before implementation/live runs;
- `run_live_pack.py`: credential-stripped live receipt capture;
- `results/live/`: first live run that exposed the CLI process-tail defect;
- `results/live-final/`: repaired final parallel/serial query receipts;
- `results/HUMAN-EVALUATION.*`: small criterion-bound usefulness table;
- `results/HOST-TRIALS.*`: generic and Claude/Fable positive protocol proof,
  a Codex failure-honesty control, and a separately labeled schema-invalid
  network-enabled Codex summary;
- `results/PRODUCT-RECEIPT.json`: final scope, hashes, decision, and limitations;
- `FIVE-MINUTE-SHOWCASE.md`: exact demo script.

Nothing here establishes general search quality, factual truth, or vendor
superiority.

The ignored `.control/raw-product-evaluation-archive/` retains the raw
pre-repair and host logs. The tracked candidate and public allowlisted export
keep normalized reports and final query receipts while
omitting local session diagnostics and the Evidence Bridge appendix.

The cross-host harness uses the JSON Schema validator in the test extra:
`python -m pip install '.[test]'`. It locally parses and validates actual host
stdout; a zero host-process exit alone is never a passing trial.
