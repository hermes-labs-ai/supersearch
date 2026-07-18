# Roadmap after Product V1

Roadmap items are hypotheses, not committed release promises.

## Core candidates

1. Split optional local-model dependencies from the retrieval-only wheel after
   clean-install compatibility is proven on supported Python versions.
2. Add explicit per-result cache-hit and retrieval-time metadata without losing
   source identity.
3. Replace string diagnostics inside source adapters with typed error codes while
   retaining human messages.
4. Add an opt-in cancellation-aware process isolation mode if real workloads
   show daemon-thread socket tails are material.

## Product evaluation candidates

- Repeat the same fixed query pack periodically with recorded network and package
  versions; do not aggregate it into a universal quality score.
- Add Windows and Linux clean-install runs in public CI.
- Test a user-supplied source plugin protocol before adding more bundled sources.

## Not planned for core

- framework-logo adapters that only wrap JSON or Python;
- answer synthesis as the default search behavior;
- truth or certification labels;
- a daemon or hosted SuperSearch account service;
- native Evidence Bridge integration while its component hold remains open.

