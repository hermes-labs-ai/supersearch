# Security Policy

## Reporting a vulnerability

If you believe you have found a security issue in SuperSearch, please report it
privately by email to **roli@hermes-labs.ai**. Do not open a public issue for
security-sensitive reports.

Please include, where possible:

- a description of the issue and its impact,
- the version or commit affected, and
- steps or a minimal proof of concept to reproduce it.

We aim to acknowledge reports within a few business days and will keep you
informed as we investigate and address the issue.

## Scope notes

SuperSearch runs locally and its default source set requires no paid API key.
Optional sources can read user-supplied credentials such as `GITHUB_TOKEN`.
It issues outbound HTTP requests to public search endpoints and can fetch result
pages; treat queries, responses, snippets, URLs, and fetched content according
to the trust boundary in `docs/PRIVACY-COST.md`. Never include a credential in a
query, receipt, issue, or vulnerability report.
