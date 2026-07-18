"""Multi-engine search for SuperSearch via ddgs metasearch."""

from dataclasses import dataclass, asdict, field
from typing import Optional
import requests
from ddgs import DDGS

from . import cache as _cache
from . import antidetect
from .diagnostics import report

# Per-request socket timeout for ddgs-backed engines. Kept at or below the
# ``search_all`` overall wall-clock budget (DEFAULT_PARALLEL_TIMEOUT = 15s) so a
# single engine call cannot, on its own, exceed the parallel deadline.
ENGINE_TIMEOUT = 10


@dataclass
class SearchResult:
    """Structured search result.

    ``sources`` records which engines surfaced this URL — populated by
    ``sources._merge_with_provenance``. Empty when a single engine returned it.
    """

    title: str
    url: str
    snippet: str
    raw_content: Optional[str] = None  # Fetched page content
    sources: list[str] = field(default_factory=list)
    query_variant: str = ""  # Expansion variant that surfaced this URL (first-seen)
    score: Optional[float] = (
        None  # Composite relevance score; set by search_all(rerank=True)
    )


class DuckDuckGoSearch:
    """Search via ddgs metasearch (Brave, DDG, Bing, Yahoo, Mojeek, Yandex)."""

    def __init__(
        self, backend: str = "auto", use_cache: bool = True, cache_ttl: int = 24 * 3600
    ):
        self.ddgs = DDGS(timeout=ENGINE_TIMEOUT)
        self.backend = backend
        self.use_cache = use_cache
        self.cache_ttl = cache_ttl

    def search(self, query: str, max_results: int = 3) -> list[SearchResult]:
        """
        Search across multiple engines via ddgs.

        Args:
            query: Search query string
            max_results: Maximum number of results to return

        Returns:
            List of SearchResult objects
        """
        cache_key = f"ddgs:{self.backend}"
        if self.use_cache:
            cached = _cache.get(cache_key, query, ttl_seconds=self.cache_ttl)
            if cached:
                return [SearchResult(**item) for item in cached[:max_results]]

        try:
            results = list(
                self.ddgs.text(query, max_results=max_results, backend=self.backend)
            )
            search_results = []

            for result in results:
                search_results.append(
                    SearchResult(
                        title=result.get("title", ""),
                        url=result.get("href", ""),
                        snippet=result.get("body", ""),
                    )
                )

            if self.use_cache and search_results:
                _cache.put(
                    cache_key,
                    query,
                    [asdict(r) for r in search_results],
                )
            return search_results
        except Exception as e:
            report(f"Error searching: {e}")
            return []

    def fetch_content(
        self, url: str, timeout: int = 10, max_chars: int = 8000
    ) -> Optional[str]:
        """
        Fetch a URL and extract clean text via lxml. No LLM, no tokens.

        Args:
            url: URL to fetch
            timeout: Request timeout in seconds
            max_chars: Max characters to return

        Returns:
            Clean page text, or None if fetch failed
        """
        try:
            headers = antidetect.random_headers()
            response = requests.get(url, timeout=timeout, headers=headers)
            response.raise_for_status()

            from lxml import html as lxml_html

            tree = lxml_html.fromstring(response.text)
            # Kill noise elements
            for tag in tree.xpath(
                "//script|//style|//nav|//footer|//header|//aside|//noscript|//iframe"
            ):
                tag.getparent().remove(tag)
            text = tree.text_content()
            # Collapse whitespace
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            clean = "\n".join(lines)
            return clean[:max_chars] if clean else None
        except Exception as e:
            report(f"Error fetching {url}: {e}")
            return None
