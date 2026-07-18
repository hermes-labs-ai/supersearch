"""
SSRN and Lexology search sources for SuperSearch.

SSRN: https://www.ssrn.com/index.cfm/en/search/ — legal papers, working papers, academic preprints
Lexology: https://www.lexology.com — law firm client alerts, practice notes, legal analysis

Both sources return structured SearchResult objects compatible with SuperSearch.
"""

import requests
from typing import Optional
from dataclasses import dataclass, field

from ddgs import DDGS


# Import or define SearchResult (compatible with SuperSearch)
try:
    from supersearch.search import SearchResult
except ImportError:
    # Fallback definition for standalone testing
    @dataclass
    class SearchResult:
        title: str
        url: str
        snippet: str
        raw_content: Optional[str] = None
        sources: list[str] = field(default_factory=list)
        query_variant: str = ""


# Try to import antidetect, fallback to basic headers
try:
    from supersearch import antidetect
except ImportError:
    class antidetect:
        @staticmethod
        def random_headers():
            return {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            }

DEFAULT_ENGINE_TIMEOUT = 10


class SSRNSource:
    """
    Search SSRN for academic papers, working papers, and legal scholarship.

    API: https://api.ssrn.com/content/v1/bindings/search
    Status: BLOCKED by Cloudflare bot protection (as of 2026-04-20)

    Returns empty list with honest failure signal if access is blocked.
    """

    BASE_URL = "https://api.ssrn.com/content/v1/bindings/search"

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """
        Search SSRN for papers and working papers.

        Args:
            query: Search query (e.g., "EU AI Act GDPR data governance")
            max_results: Max results to return

        Returns:
            List of SearchResult objects, or empty list if access is blocked
        """
        try:
            params = {
                "query": query,
                "start": 0,
                "count": max_results,
            }
            resp = requests.get(
                self.BASE_URL,
                params=params,
                headers=antidetect.random_headers(),
                timeout=DEFAULT_ENGINE_TIMEOUT,
            )

            # Check for access denial
            if resp.status_code == 403 or "Just a moment" in resp.text:
                return [SearchResult(
                    title="SSRN Access Blocked",
                    url=self.BASE_URL,
                    snippet="SSRN API is behind Cloudflare bot protection. Use web search instead.",
                    sources=["ssrn_blocked"],
                )]

            resp.raise_for_status()
            data = resp.json()

            results = []
            for paper in data.get("papers", []):
                title = paper.get("title", "Untitled")
                ssrn_id = paper.get("id", "")
                url = f"https://ssrn.com/abstract={ssrn_id}" if ssrn_id else ""
                snippet = paper.get("keywords_str", "")[:150]

                if url:
                    results.append(SearchResult(
                        title=title,
                        url=url,
                        snippet=snippet,
                    ))

            return results
        except requests.Timeout:
            return [SearchResult(
                title="SSRN Timeout",
                url=self.BASE_URL,
                snippet="SSRN search timed out",
                sources=["ssrn_timeout"],
            )]
        except Exception as e:
            return [SearchResult(
                title=f"SSRN Error: {type(e).__name__}",
                url=self.BASE_URL,
                snippet=str(e)[:150],
                sources=["ssrn_error"],
            )]


class LexologySource:
    """
    Search Lexology for legal analysis, client alerts, and practice notes.

    Web: https://www.lexology.com
    Strategy: Search via site: operator on DuckDuckGo, then fetch individual articles
    Status: Search works; direct article fetch returns 403 (likely requires JS/auth)

    Returns search results even if fetch fails, to enable multi-engine result merging.
    """

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """
        Search Lexology for legal analysis articles via site: search on DuckDuckGo.

        Args:
            query: Search query (e.g., "EU AI Act Article 14 compliance obligations")
            max_results: Max results to return

        Returns:
            List of SearchResult objects (search-only; individual articles may require auth)
        """
        try:
            ddgs = DDGS(timeout=DEFAULT_ENGINE_TIMEOUT)
            site_query = f"site:lexology.com {query}"

            results = []
            for hit in ddgs.text(site_query, max_results=max_results):
                title = hit.get("title", "")
                url = hit.get("href", "")
                snippet = hit.get("body", "")[:150]

                if title and url:
                    results.append(SearchResult(
                        title=title,
                        url=url,
                        snippet=snippet,
                    ))

            return results
        except requests.Timeout:
            return [SearchResult(
                title="Lexology Timeout",
                url="https://www.lexology.com",
                snippet="Lexology search timed out",
                sources=["lexology_timeout"],
            )]
        except Exception as e:
            return [SearchResult(
                title=f"Lexology Error: {type(e).__name__}",
                url="https://www.lexology.com",
                snippet=str(e)[:150],
                sources=["lexology_error"],
            )]

    def fetch(self, url: str) -> Optional[str]:
        """
        Attempt to fetch Lexology article content.

        Status: Articles return 403 (requires JavaScript/authentication)

        Args:
            url: Article URL from Lexology

        Returns:
            Article text if available, None otherwise
        """
        try:
            headers = antidetect.random_headers()
            resp = requests.get(url, headers=headers, timeout=DEFAULT_ENGINE_TIMEOUT)

            if resp.status_code == 403:
                return None

            resp.raise_for_status()

            # Try to extract article text from HTML
            # Most Lexology articles have content in a specific div
            # but this requires proper HTML parsing and may still hit JS/auth walls
            return resp.text[:500]  # Return partial text for inspection
        except Exception:
            return None
