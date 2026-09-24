# Distribution and source exports

Install the Python distribution `hermes-supersearch`. Its import package and
CLI are both `supersearch`; the license is Apache-2.0.

## Build and check a release candidate

From a clean checkout with Python 3.10+:

```bash
python -m pip install -e '.[test]' build twine
python -m pytest
python scripts/export_public_candidate.py --destination ../supersearch-export
cd ../supersearch-export
python -m build
python -m twine check dist/*
python -m venv .venv
.venv/bin/python -m pip install dist/*.whl
.venv/bin/supersearch search --help
.venv/bin/supersearch search --list-sources
```

On Windows, use `.venv\Scripts\python` and `.venv\Scripts\supersearch`.
A live search additionally requires access to the selected public sources.
See [privacy and cost](PRIVACY-COST.md) and [limitations](LIMITATIONS.md).

## Public source boundary

`scripts/public-files.txt` lists each reviewed export file explicitly. Adding a
file to a directory does not authorize its export. Review additions for user,
contributor, or reproducibility value before adding them to this list. Keep
operating notes, session output, local configuration, credentials, and private
integration details out of source exports and package archives.

The exporter reads committed bytes from a clean Git HEAD, checks selected text
for local paths, and rejects symbolic links. It validates the full selection
before writing the destination. `PUBLIC-EXPORT-RECEIPT.json` records file hashes
and the source commit; it is generated metadata, not part of the package API.
Run `python scripts/export_public_candidate.py --check` to verify that every
tracked file in this public repository is covered by the reviewed list.
Automated checks supplement content review; they cannot determine whether new
prose reveals private operating knowledge.

Published evaluation data includes fixed queries, criteria, measurements,
limitations, and normalized host reports. Machine-specific logs are not needed
to install or use the package. [Evaluation documentation](../product_evaluation/README.md)
distinguishes public evidence from reported host outcomes.

Source cleanup does not erase prior commits, tags, or released archives.
