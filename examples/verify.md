# Verify command patterns

## Human receipt

```bash
supersearch verify "Python 3.13 was released in October 2024" --deep
```

Read the verdict together with its reason and availability fields. For each
source, confirm whether `evidence_kind` is `fetched_page` or `search_snippet`.
A failed deep fetch is retained as `fetch_status=failed` and is not described as
page-verified.

## Machine receipt

```bash
supersearch verify "Python 3.13 was released in October 2024" --deep --json
```

The output schema is `supersearch.verify.v1`. Consumers should branch on
`verdict`, then inspect `retrieval_status`, `evaluator_status`, `sources`,
`numeric_conflicts`, `freshness`, `limitations`, and `nonclaims`.

## Expected offline behavior

Running without a reachable retrieval path or configured local evaluator is a
valid negative control:

```bash
OLLAMA_URL=http://127.0.0.1:9 \
  supersearch verify "Python 3.13 was released in October 2024" --json
```

The receipt must be `UNVERIFIED`; the precise reason depends on whether sources
were retrieved. An unavailable local evaluator cannot be replaced by a cached
positive label.

These examples do not prescribe an expected factual verdict for the example
claim. Any non-`UNVERIFIED` verdict is scoped only to the evidence in that run.
