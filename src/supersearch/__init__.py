"""SuperSearch - deadline-bounded search fan-out for agents and engineers."""

__version__ = "0.11.0"
__author__ = "Hermes Labs"

from .search import DuckDuckGoSearch, SearchResult
from .product import search as fanout_search
from .sources import (
    HackerNewsSearch,
    GitHubSearch,
    ArxivSearch,
    SemanticScholarSearch,
    SearXNGSearch,
    search_all,
)

__all__ = [
    "DuckDuckGoSearch",
    "SearchResult",
    "fanout_search",
    "HackerNewsSearch",
    "GitHubSearch",
    "ArxivSearch",
    "SemanticScholarSearch",
    "SearXNGSearch",
    "search_all",
]


def __getattr__(name: str):
    """Keep the optional reranker import-compatible without loading it at startup."""

    if name == "LocalReranker":
        from .rerank import LocalReranker

        return LocalReranker
    raise AttributeError(name)
