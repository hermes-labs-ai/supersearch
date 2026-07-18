"""Round-3 connector fleet (v0.10) — reach-gap closers surfaced by Wave 2A.

Each connector targets a source class the free-engine stack couldn't reach:

- ``eurlex_source``        — EU Official Journal / EUR-Lex SPARQL + direct CELEX
- ``ssrn_lexology_source`` — paywalled legal analysis via author archives + SSRN
- ``github_deep_source``   — beyond top-level GitHub search: code + issues
- ``corp_signal_source``   — OpenCorporates + SEC EDGAR (M&A/pivot/shutdown signal)

Each class exposes ``search(query, max_results) -> list[dict]``; the supersearch
adapter in ``sources.py`` converts dicts to ``SearchResult``. Wired into
``_source_map()`` as: ``eurlex``, ``lexology``, ``ssrn``, ``github_deep``,
``opencorp``, ``edgar``.
"""

from .eurlex_source import EurLexSource
from .ssrn_lexology_source import LexologySource, SSRNSource
from .github_deep_source import GitHubDeepSource
from .corp_signal_source import OpenCorporatesSource, SECEdgarSource

__all__ = [
    "EurLexSource",
    "LexologySource",
    "SSRNSource",
    "GitHubDeepSource",
    "OpenCorporatesSource",
    "SECEdgarSource",
]
