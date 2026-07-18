# Contributing

## Getting started

1. Fork the repository.
2. Create a feature branch from `main`.
3. Install: `python -m pip install -e '.[test]'`
4. Make your changes.

## Running tests

```bash
python -m pytest -v
```

## Adding a new search engine

1. Create a scraper in `src/supersearch/`.
2. Return `SearchResult` objects or use the documented adapter seam.
3. Report failure through `diagnostics.report` so Product V1 can distinguish
   failure from an empty search.
4. Register the source in `_source_map`.
5. Add offline parsing, exception, provenance, and timeout tests.

## Code style

- Line length: 100
- Target: Python 3.10+

## Pull requests

1. Keep changes focused — one feature or fix per PR.
2. Add tests for new engines or scrapers.
3. Update `CHANGELOG.md` under an `Unreleased` section.
4. Open a PR against `main` with a clear description of what and why.
