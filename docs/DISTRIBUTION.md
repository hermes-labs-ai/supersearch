# Releases and source archives

The Python distribution is `hermes-supersearch`. Its import package and CLI are
both `supersearch`; the license is Apache-2.0.

## Build and validate

Use a clean, committed checkout with Python 3.10+:

```bash
python -m pip install -e '.[test]' build twine 'ruff==0.15.14'
ruff check .
python -m pytest
python scripts/export_public_candidate.py --check
python scripts/export_public_candidate.py --destination ../supersearch-export
cd ../supersearch-export
python -m build
python -m twine check dist/*
python scripts/check_installed.py dist/*.whl dist/*.tar.gz
python -m venv .venv
.venv/bin/python -m pip install dist/*.whl
.venv/bin/supersearch search --help
.venv/bin/supersearch search --list-sources
```

The export destination must not already exist. On Windows, use
`.venv\Scripts\python` and `.venv\Scripts\supersearch` for the installed commands.
A live search additionally requires access to the selected sources; see
[privacy and cost](PRIVACY-COST.md) and [limitations](LIMITATIONS.md).

The installed check (Linux/macOS) creates two fresh virtual environments outside
the checkout, installs the wheel and sdist separately, and runs Python in isolated
mode with a clean environment and working directory. Installation may download
dependencies; Python and search CLI probes deny socket access and use controlled
adapters. A separate direct console `--version` smoke check runs without the socket
guard; it performs no search.
The real fan-out and CLI must produce schema-valid partial and unavailable
receipts, preserve provenance, separate stderr, and return exits 0 and 3. Both the
installed console entry script and `python -m supersearch` dispatch are exercised.
The schema and explicit source resources come from the sdist. Negative controls
temporarily break partial status and remove a module inside each disposable
installation; both must fail before a restored installation passes. This checks
distribution behavior, not live search availability or relevance. Use `--report`
to save the artifact hashes, import origins, receipts and control outcomes.

## Source selection

`scripts/public-files.txt` is the exact list of reviewed source-export files.
Add new source, documentation, test, or integration files explicitly. The
`--check` command rejects tracked files missing from the list and listed files
missing from the commit. CI and the tag-release workflow run this check.

The exporter reads committed bytes from Git HEAD, checks text for local paths,
and rejects symbolic links and binary files. It validates the complete selection
before creating the destination. Review file contents as well as the file list;
path checks do not detect every credential or machine-specific detail.

`PUBLIC-EXPORT-RECEIPT.json` records the source commit and each exported file's
SHA-256 hash. It is generated export metadata and is not included in the Python
wheel or source distribution.

`MANIFEST.in` selects documentation, examples, tests, integration files, and
[evaluation data](../product_evaluation/README.md) for the source distribution.
The wheel contains the Python package and standard distribution metadata.
Inspect both archives after changes to either source-selection list.

## Publishing

The `Publish to PyPI` workflow builds and checks distributions for `v*` tags.
The tag version must match `pyproject.toml`. Publishing uses the repository's
configured PyPI environment and trusted-publishing credentials.

## 0.11.1 - 2026-10-20

### Fixed

- Preserve connector failures, rate limits and invalid response envelopes in
  source status rather than returning a clean empty result. GitHubDeep keeps
  successful partial results while reporting failed issue/README requests, and
  no longer requests the unsupported `/contents/wiki` endpoint (#25).
- Prevent concurrent writes to the same cache key from sharing a temporary
  file, avoiding corrupted JSON and failed writes (#7).
- Handle root `--version` without starting a legacy positional search (#5).

### Packaging

- Include the portable agent plugin in the repository and source distribution,
  with a pinned receipt workflow (#8).
- Build distributions from an explicitly reviewed public source selection,
  checked in package CI and tag publishing (#16, #21, #22).

### Compatibility and upgrade

Python 3.10+ and the `supersearch.search.v1` receipt schema are unchanged.
Custom dict-based source adapters must return a list/tuple in `results`;
malformed envelopes now report errors. No live-source availability or search
quality improvement is claimed.

```sh
python -m pip install --upgrade 'hermes-supersearch==0.11.1'
supersearch --version
supersearch search --list-sources
```
