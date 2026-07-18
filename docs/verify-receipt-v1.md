# Verify Receipt V1 Contract

Status: frozen before implementation for SUPERSEARCH VERIFY V1.

## Highest-impact problem

`supersearch verify` currently labels search snippets as `exact_quote`, and deep
mode can classify fetched page text while displaying a different snippet as the
evidence. Model failures are collapsed into `NEUTRAL`, so a partial failure can
still produce a positive verdict. The smallest durable correction is a
versioned receipt that binds every classification to an explicit evidence kind,
keeps evaluator availability separate from semantic labels, and makes the
default integrity gate package-owned and offline.

## Verdict evaluator

The top-level verdict describes the relationship between the claim and the
listed evidence. It is not a ground-truth or source-authority judgment.

| Condition | Verdict | Reason |
|---|---|---|
| Retrieval unavailable or no sources | `UNVERIFIED` | `retrieval_unavailable` or `no_sources` |
| Model unavailable, invalid, or any required classification incomplete | `UNVERIFIED` | `evaluator_unavailable` |
| All valid labels are neutral | `UNVERIFIED` | `no_stance_evidence` |
| Entailment is dominant and dissent is below the frozen threshold | `SUPPORTED` | `entailment_dominant` |
| Contradiction is dominant and dissent is below the frozen threshold | `CONTRADICTED` | `contradiction_dominant` |
| Both stance labels meet the frozen conflict rule | `CONFLICTING` | `mixed_evidence` |
| Same claim-relevant entity and unit have one unambiguous value per URL and disagree by more than 10% across at least two distinct URLs, with an operational evaluator | `CONFLICTING` | `numeric_conflict` |
| Numeric conflict is detected while the evaluator is unavailable | `UNVERIFIED` | `evaluator_unavailable`; keep the separate numeric signal |

NLI aggregation uses only completed classifications. `ENTAIL` or `CONTRADICT`
is dominant at 60% or more of non-neutral labels only when the opposing share is
strictly below 20%. A 20% or larger minority produces `CONFLICTING`.

## Evidence contract

Each source contains:

- `url`, `title`, `engines`, and `query_variant` retrieval provenance;
- `search_snippet`, always named as a search snippet;
- `evidence_kind`: `search_snippet` or `fetched_page`;
- `fetch_status`: `not_requested`, `fetched`, `failed`, or `not_attempted`;
- `evidence_excerpt`, a literal substring of the named evidence basis with no
  synthetic ellipsis;
- `evidence_sha256`, computed over the complete text passed to the evaluator;
- `nli_label` and independent `nli_status`;
- heuristic `date`, `date_basis`, and `freshness_score` when a date is detected.

When deep fetch succeeds, the receipt excerpt and classification input both
come from the fetched page representation. When it fails, both fall back to the
search snippet and the failed fetch remains explicit. Sources outside the deep
fetch limit are `not_attempted`, never `failed` or page-verified.

## JSON receipt schema

The stable top-level keys are:

```text
schema_version, claim, verdict, verdict_reason,
retrieval_status, evaluator_status, deep_requested,
sources, numeric_conflicts, freshness, engines_used,
limitations, nonclaims, cost_usd
```

`schema_version` is `supersearch.verify.v1`. Freshness records one UTC `as_of`
date, `dated_sources`, `total_sources`, and `mean`; it is a heuristic coverage
signal rather than a publication-date guarantee. A CLI run computes `as_of`
once. Tests may inject it to prove byte-identical repeated output.

## Claims the receipt may make

- The stated evaluator classified the stated evidence basis with the recorded label.
- The excerpt is a literal substring of that basis.
- The listed URL, engine names, and query variant are retrieval provenance.
- A numeric conflict met the disclosed syntactic rule.
- Freshness used the disclosed heuristic and coverage.

## Strict nonclaims

- No ground truth, factual accuracy, certification, completeness, or source authority.
- No claim that a search snippet was verified on its live page.
- No claim that URL presence proves current reachability.
- No claim that a detected date is an authoritative publication date.
- No claim that numeric disagreement proves semantic contradiction.
- No claim that sources are independent.
- No claim that deep verification occurred after a fetch fallback.
- No positive verdict when retrieval or the required evaluator is unavailable.

## Frozen test matrix

| Area | Positive control | Negative/fallback control | Required proof |
|---|---|---|---|
| Provenance | Search snippet evidence | Long snippet | Explicit kind; excerpt is a literal substring; no synthetic ellipsis |
| Deep fetch | Page fetch succeeds | Mixed success/failure and outside-top-K | Output basis matches NLI input; fallback status is explicit |
| Retrieval | Sources returned | Exception/no sources | No-source and unavailable cases are `UNVERIFIED` |
| Evaluator | Valid exact-token outputs | Full/partial outage, malformed or multi-token response | Outage/invalid evaluation cannot yield a positive or conflicting top verdict |
| Cache | Reachable evaluator and valid cache | Positive cache while evaluator unavailable | Unavailable evaluator remains `UNVERIFIED` |
| Numeric | >10% same entity/unit, two URLs with one value each | Exactly 10%, unrelated entity/unit, one URL, or an ambiguous multi-value URL | Separate enriched signal with per-value URL/excerpt/provenance |
| Freshness | Fixed dated evidence | Unknown/future dates | Fixed `as_of`, explicit coverage, deterministic score |
| CLI/schema | Markdown and JSON | No claim, invalid source bounds | Stable keys/types, exit codes, clean stdout/stderr |
| Standalone | Package-owned invariant gate | Search for external paths/scripts | No ambient filesystem dependency; no maintainer-home tool default |
| Retrieval defaults | Timeout-bounded package connectors | No Ollama and no ddgs-backed connector | Default Verify routing is package-owned and cannot hang on a ddgs/primp call |
| Docs | Five-minute Verify flow | Offline/no Ollama | Commands are source-bound and offline failure is truthful |
| Packaging | Wheel/sdist and local install | Empty cache/no network | Package build/install needs no ambient checkout or external script |
| Determinism | Same frozen inputs twice | Cache cold/warm where applicable | Byte-identical JSON for a fixed `as_of` |

## Recommended implementation path and trade-offs

Keep the existing retrieval, NLI, deep-fetch, and fact-audit seams. Add
structured status alongside them rather than replacing SuperSearch with a new
search wrapper. Retain `classify` and `retrieve` compatibility wrappers while
the Verify pipeline consumes status-bearing APIs. This adds a small schema
surface but avoids silently treating availability failures as semantic
neutrality.

Public destination, product positioning, package version, release readiness,
and canonical adoption remain owner decisions outside this contract.
