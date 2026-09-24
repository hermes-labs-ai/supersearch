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
python -m venv .venv
.venv/bin/python -m pip install dist/*.whl
.venv/bin/supersearch search --help
.venv/bin/supersearch search --list-sources
```

The export destination must not already exist. On Windows, use
`.venv\Scripts\python` and `.venv\Scripts\supersearch` for the installed commands.
A live search additionally requires access to the selected sources; see
[privacy and cost](PRIVACY-COST.md) and [limitations](LIMITATIONS.md).

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
