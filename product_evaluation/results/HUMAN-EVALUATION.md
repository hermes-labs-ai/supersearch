# Human-readable Product V1 evaluation

Applied to the final parallel receipts under the criteria frozen in
`PREREGISTRATION.md`. This is one review of 27 result cards, not a truth test or
a general relevance estimate.

| Query | Results | Useful | Useful adapters | First useful | Honest observation |
|---|---:|---:|---|---:|---|
| Q1: Python 3.12 distutils migration | 6 | 3 (50%) | DDGS | 1 | Concrete migration/removal sources appeared first; all three arXiv results were off-topic. |
| Q2: SQLite vector extensions | 12 | 6 (50%) | DDGS, GitHub | 1 | Release/docs/comparison and implementation repositories were useful; fixed broad fan-out added noise. |
| Q3: RFC 9116 path | 9 | 6 (67%) | DDGS, GitHub | 1 | The standard and implementations were useful; all three arXiv path matches were off-topic. |
| **Total** | **27** | **15 (56%)** | — | **3/3 at rank 1** | Every query produced a useful first result; broad retrieval still needs query-aware source choice or optional ranking. |

Distinct useful domains: 7. The result set was usable for source scouting, but
the off-topic academic tail is a concrete limitation against claims of universal
multi-source value.

