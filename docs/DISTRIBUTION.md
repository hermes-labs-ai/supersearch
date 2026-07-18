# Distribution plan

## Identity

- Public repository name: `supersearch`.
- Python distribution: `hermes-supersearch` (the case-insensitive
  `Super-Search` name is occupied on PyPI).
- Import package and CLI: `supersearch`.
- License: Apache-2.0.

Recheck package and repository availability immediately before publication.
This candidate does not reserve or create either identity.

## Exact local artifacts

1. Build the test wheel from the final clean internal Git head.
2. Install that wheel into a fresh Python 3.10+ environment.
3. Run offline tests, `supersearch search --help`, `--list-sources`, the
   deterministic deadline control, and one live receipt.
4. Create the public source tree with:

   ```bash
   python scripts/export_public_candidate.py --destination <empty-local-path>
   ```

5. Compare the generated `PUBLIC-EXPORT-RECEIPT.json` to the final lifecycle
   receipt. Build any publication sdist and wheel from that allowlisted tree,
   then repeat the clean-install controls before any remote action.

The public export is allowlisted from the exact Git head. It omits the internal
Evidence Bridge component, raw host logs, local controls, and the pre-repair
pack. This avoids promoting the adapter into the product and prevents local
paths/session diagnostics from becoming public. Product code, tests, docs,
normalized evaluation, and final live query receipts remain. `MANIFEST.in`
also enumerates the sanitized evaluation files explicitly; it does not recurse
through internal host logs or pre-repair results. The internal historical
changelog is intentionally excluded because it contains machine-relative tool
paths from before the public Product V1 boundary.

## Separate authority required

Creating a remote repository, pushing, publishing a package, creating a release,
or adopting the component in HAL/Fable all remain outside this candidate. No
publication step is performed by the Product V1 work.
