# Current-release frozen-pack rerun — 24 October 2026

Local evaluation for [issue #24](https://github.com/hermes-labs-ai/supersearch/issues/24). No publication or issue update was made. No search, ranking, source-adapter, harness or preregistration bytes changed.

## Identity and protocol

PyPI selected `hermes-supersearch` **0.11.1**, wheel `hermes_supersearch-0.11.1-py3-none-any.whl`, SHA-256 `0d2625894cdc59e98f58099249cb01cd4dd7eb46b432f7c495b65b0822741849`. The wheel installed into a new base venv on Python **3.14.7**. [ENVIRONMENT.json](ENVIRONMENT.json) records PyPI selection, upload date, platform and resolved dependencies. The evaluation harness came from current main `a1316181136aafa9a4a6745831c783c99524a6d4`.

The unchanged frozen Q1–Q3 queries used `ddg,hn,github,arxiv`, three results per source, a 12-second parallel deadline, no reranking and an initially empty isolated cache. An allowlisted subprocess environment contained only PATH, isolated HOME/TMPDIR, LANG and PYTHONUTF8; no model or search credentials were supplied. The native harness additionally removes its six named credential variables. Serial/parallel order remained Q1 serial-first, Q2 parallel-first, Q3 serial-first. The cache is reused across calls, so the second mode may benefit.

[PUBLIC-LIVE-SUMMARY.json](PUBLIC-LIVE-SUMMARY.json) preserves the machine measurements and raw-summary hash, with only the local cache path normalized. Six unchanged query receipts and their stderr files are beside it. The original raw machine summary remains with the isolated local execution environment. [VALIDATION.json](VALIDATION.json) binds artifacts and unchanged historical/preregistration bytes to their hashes.

## Observed comparison

Historical values below come from the retained [0.11.0 summary](../PUBLIC-LIVE-SUMMARY.json) and [human labels](../HUMAN-EVALUATION.json). Durations are process wall seconds.

| Query | 0.11.0 parallel status/results/domains | 0.11.1 parallel status/results/domains | Old/new parallel seconds | Old/new serial seconds | Old/new useful count |
| --- | --- | --- | --- | --- | --- |
| Q1 | ok / 6 / 3 | ok / 6 / 4 | 8.668 / 0.438 | 22.590 / 3.053 | 3 / 3 |
| Q2 | ok / 12 / 5 | partial / 9 / 3 | 12.341 / 3.208 | 14.095 / 3.550 | 6 / 4 |
| Q3 | ok / 9 / 4 | ok / 9 / 5 | 2.509 / 0.395 | 16.273 / 2.604 | 6 / 6 |

Current parallel calls returned **24** unique result URLs within their respective receipts, versus **27** historically. Current criterion labels count **13/24** useful, versus historical **15/27**; useful rank-1 results occurred in **2/3** current queries versus **3/3** historically. These are sums across per-query results, not a claim that all URLs across queries are globally distinct. [CRITERION-LABELS.json](CRITERION-LABELS.json) contains a boolean and rationale for each result, bound to the exact parallel receipt.

The current labels were applied by one Codex agent, not a human reviewer. Historical labels came from one human. Both inspect returned titles/snippets rather than fetching every page. Q2's three HN announcement-only snippets were conservatively excluded, consistent with the historical exclusion of non-substantive HN results. Its three implementation repositories and one SQLite implementation paper were counted. Alternative judgment on announcements can change the count; preserved individual labels make that inspectable.

Q2 DDG reports `failed` with `Error searching: No results found.` in both modes; the overall receipt is `partial`, with nine results from HN/GitHub/arXiv. This is source-error evidence, not proof of zero matching pages. HN and GitHub report successful empty results for Q1, and HN does so for Q3. Thus empty and failed states remain visible and different in this live run. No live source timed out during this pack.

The shorter current timings are descriptive observations. Different Python/dependency versions, public indexes, networks and cache effects prevent attributing them to the 0.11.1 code change. Q2 source availability differs from the old parallel run, so it is not equal-completion evidence. The query mix was deliberately not optimized; off-topic arXiv results remain in Q1 and Q3.

## Current deterministic controls

Two unchanged native test files were copied outside the source checkout and run with `--noconftest` against the installed wheel, avoiding the repository conftest's `src/` injection. **67 passed**, with zero failures, errors or skips. [WHEEL-CONTROLS.json](WHEEL-CONTROLS.json) records source hashes, test counts and controls; [console output](WHEEL-CONTROLS.txt) is retained. Default reranking is false and base installation requires no model dependency. These fixture checks do not establish retrieval quality.

The unchanged [deadline probe](../../deadline_probe.py) tested a 250 ms deadline with a synthetic slow source that registers a 30-second exit hook. The current wheel returned a partial one-result receipt in **252.999 ms** and exited in **339.707 ms**; fast completed and slow timed out. [DEADLINE-CONTROL.json](DEADLINE-CONTROL.json) records PASS. This is a deterministic process control, not a live-source latency bound.

## Disposition and limits

The current clean install, direct CLI contract, deterministic controls and criterion-useful receipts are demonstrated for this bounded pack. New Codex/Claude model-host trials were not run; historical host reports retain their original limitations. This is not a new standalone-product acceptance decision, general relevance/recall/freshness/latency result, factual-truth check, detector comparison or vendor-superiority claim. Retrieval-route provenance does not establish authorship, authority or independence.

Issue #24's local evaluation/comparison work is substantively performed. Its requested public delivery remains unmet because this campaign authorizes no publication or submissions. The artifacts and branch are ready for a separately authorized review/delivery step; the issue remains open. No rerun or method redesign is needed merely because the result is mixed.
