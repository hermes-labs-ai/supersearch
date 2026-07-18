# Exact public positioning thesis

## Headline

**One query across web, code, community, and research sources. One deadline.**

## Product thesis

SuperSearch is a local search fan-out for agents and engineers who need a useful
source set before analysis. It queries heterogeneous public surfaces
concurrently, contains slow sources under one caller-visible deadline, merges
duplicate URLs without losing retrieval-route provenance, and returns a
versioned receipt that distinguishes completed, failed, degraded, and timed-out
sources. The default path needs no paid search key and invokes no LLM.

## What it refuses to claim

SuperSearch returns search evidence, not an answer. It does not certify truth,
promise exhaustive or uniformly fresh coverage, claim better relevance than a
hosted search provider, or treat a source identity as proof of authorship,
authority, or independence. A Verify `SUPPORTED` verdict means that named
retrieved evidence supports a claim under the recorded evaluator; it is not a
truth or certification label.

## When agents should use it

Use SuperSearch when one task benefits from web, code, community, or academic
source diversity and must finish within a bounded latency budget, especially
for migration scouting, open-source landscape mapping, standards lookup, and
pre-analysis evidence collection. Call one provider directly when one index is
enough. Use a managed search/research service when hosted extraction, synthesis,
scale, or an SLA is the actual job.

## Surface hierarchy

- Core: `supersearch search`, `fanout_search`, source-state receipts.
- Optional: source-bound Verify.
- Experimental: local reranking (outside the total-deadline contract), research,
  routing, expansion, and scraper utilities.
- Internal: Evidence Bridge shadow adapter, status `PHASED_COMPONENT_HOLD`.
