---
name: supersearch
description: Collect bounded public search evidence with the pinned hermes-supersearch 0.11.0 CLI. Use when the user wants source discovery across web, GitHub, Hacker News, and arXiv under one deadline, with a validated supersearch.search.v1 receipt that shows which sources completed, failed, or timed out. It returns evidence (URLs, titles, snippets, source status), never an answer or synthesis.
---

SuperSearch fans one query out to public search surfaces under one total
deadline and writes exactly one `supersearch.search.v1` JSON receipt to stdout
(https://github.com/hermes-labs-ai/supersearch). It needs no paid key and makes
no LLM call on this path. The receipt is search evidence, not an answer: never
present it as a verified fact, a summary of the truth, or a synthesis.

The query leaves the machine and is sent to the selected public services. Do
not put secrets, credentials, or private data in the query.

1. Pick a runner and keep it for every step. Prefer `uvx` (no install, no PATH
   change):
   ```
   uvx --from hermes-supersearch==0.11.0 supersearch search --version
   ```
   It must print `0.11.0`. If `uvx` is unavailable, use a throwaway venv:
   ```
   python3 -m venv .supersearch-venv
   .supersearch-venv/bin/python -m pip install hermes-supersearch==0.11.0 "jsonschema>=4.23"
   .supersearch-venv/bin/supersearch search --version
   ```
   Keep the exact `==0.11.0` pin. Do not run bare `supersearch --version` or
   `supersearch "<query>"`: in 0.11.0 those reach the legacy positional
   command, which searches for the literal text and may call a local model.
   Only the `search` subcommand is the bounded, LLM-free path.

2. Run one bounded search. Use an explicit, limited source mix, a small
   per-source cap, and a total deadline. Pass the user's query as one
   single-quoted argument (escape any single quote inside it):
   ```
   uvx --from hermes-supersearch==0.11.0 supersearch search '<query>' \
     --sources ddg,hn,github,arxiv \
     --max-per-source 3 \
     --deadline 12 \
     > receipt.json
   ```
   Stay within these bounds unless the user asks otherwise: at most the four
   sources above, `--max-per-source` no higher than 5, `--deadline` no higher
   than 30 seconds. `supersearch search --list-sources` prints every
   registered source; some need a user-supplied credential or service. Source
   diagnostics go to stderr; stdout holds only the receipt.

   Exit codes: `0` receipt written (`ok`, `partial`, or `no_results`); `2`
   invalid request (bad source name or bound), no receipt; `3` receipt written
   with status `unavailable`. Run it once. Do not loop retries on failed
   sources; at most one bounded retry, otherwise report the partial receipt.

3. Validate the receipt against the published schema from the same release
   tag before using it:
   ```
   curl -fsSL -o search-receipt-v1.schema.json \
     https://raw.githubusercontent.com/hermes-labs-ai/supersearch/v0.11.0/docs/search-receipt-v1.schema.json
   uv run --no-project --with "jsonschema>=4.23" python - <<'PY'
   import json
   from jsonschema import Draft202012Validator, FormatChecker
   schema = json.load(open("search-receipt-v1.schema.json"))
   receipt = json.load(open("receipt.json"))
   errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(receipt))
   print("receipt valid" if not errors else "receipt INVALID")
   for error in errors:
       print("-", list(error.path), error.message)
   PY
   ```
   With the venv runner, use `.supersearch-venv/bin/python -` instead of
   `uv run ... python -`. If validation fails, report that and do not use
   the results.

4. Report the evidence using the product's own status meanings:
   - Receipt `status`: `ok` = results and every source completed; `partial` =
     usable results but at least one source was degraded, failed, or timed
     out; `no_results` = sources completed with zero matches; `unavailable` =
     source failures prevented any result.
   - Per source (`sources[]`): `completed`, `degraded`, `failed`, or
     `timed_out`, with `result_count` and `diagnostics`. A completed source
     with zero matches is not a failure.
   - State the receipt status and every source that was not `completed`
     before listing results. Never hide a `partial` receipt.
   - List results as rank, title, URL, and the `sources` that surfaced each
     one. Keep `query` and `retrieved_at`. Offer `receipt.json` as the
     artifact.

Constraints:
- Evidence only. Do not write a synthesized answer, verdict, or summary and
  attribute it to SuperSearch. If the user wants analysis, label it as your
  own reading of the listed URLs, which you have not verified by this step.
- A result, snippet, or source provenance does not prove truth, authorship,
  independence, freshness, or completeness; a completed search is not
  exhaustive.
- DDGS-backed results may come from a local cache for up to 24 hours. Set
  `SUPERSEARCH_CACHE_DIR` to keep cache writes in a chosen directory.
- Do not use the `verify`, `research`, or legacy positional commands from this
  skill; they are outside this bounded evidence path.
