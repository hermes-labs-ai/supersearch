"""
Additional search sources for SuperSearch.

Each source implements the same interface as DuckDuckGoSearch:
    search(query: str, max_results: int) -> list[SearchResult]

Sources:
    - HackerNewsSearch: Algolia HN API (no auth, real-time)
    - GitHubSearch: GitHub Search API (token optional, 5000/hr auth vs 60/hr unauth)
    - ArxivSearch: arXiv API (no auth, academic papers)
    - SemanticScholarSearch: Semantic Scholar API (no auth, academic)
    - TwitterSearch: Twitter/X via ddgs site-scoped search (no auth, real-time)
    - SearXNGSearch: Self-hosted SearXNG meta-search (optional, best coverage)
"""

import os
import queue as _queue
import threading
import time
import requests
import xml.etree.ElementTree as ET
from typing import Optional
from .search import SearchResult
from . import antidetect
from .diagnostics import capture_diagnostics, report

# Per-engine timeouts (seconds). Individual engines should fail independently;
# if one is slow, the orchestrator should move on without it.
DEFAULT_ENGINE_TIMEOUT = 10
DEFAULT_PARALLEL_TIMEOUT = 15


# ---------------------------------------------------------------------------
# Query trimming for AND-logic APIs (HN Algolia, GitHub Search)
# Long queries (7+ words) return zero results because every word must match.
# This extracts the most important keywords after removing stop words.
# ---------------------------------------------------------------------------

_STOP_WORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "shall",
        "can",
        "need",
        "dare",
        "ought",
        "used",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "between",
        "out",
        "off",
        "over",
        "under",
        "again",
        "further",
        "then",
        "once",
        "here",
        "there",
        "when",
        "where",
        "why",
        "how",
        "all",
        "each",
        "every",
        "both",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "nor",
        "not",
        "only",
        "own",
        "same",
        "so",
        "than",
        "too",
        "very",
        "just",
        "because",
        "but",
        "and",
        "or",
        "if",
        "while",
        "although",
        "though",
        "that",
        "this",
        "these",
        "those",
        "what",
        "which",
        "who",
        "whom",
        "its",
        "it",
        "i",
        "me",
        "my",
        "we",
        "our",
        "you",
        "your",
        "he",
        "him",
        "his",
        "she",
        "her",
        "they",
        "them",
        "their",
        "about",
        "up",
        "down",
        "any",
        "much",
        "many",
        "also",
        "well",
        "still",
    }
)


def _trim_query(query: str, max_keywords: int = 5) -> str:
    """Extract up to max_keywords content words from a query, dropping stop words."""
    words = query.split()
    if len(words) <= max_keywords:
        return query
    keywords = [w for w in words if w.lower() not in _STOP_WORDS]
    if not keywords:
        return query
    return " ".join(keywords[:max_keywords])


# ---------------------------------------------------------------------------
# Hacker News (via Algolia API)
# ---------------------------------------------------------------------------


class HackerNewsSearch:
    """
    Search Hacker News via Algolia API.
    No auth required. Real-time index.

    Use for: finding HN threads, Show HN posts, discussions about specific topics.
    """

    BASE_URL = "https://hn.algolia.com/api/v1/search"

    def search(
        self, query: str, max_results: int = 5, search_type: str = "story"
    ) -> list[SearchResult]:
        """
        Search HN stories and comments.

        Args:
            query: Search query
            max_results: Max results to return
            search_type: 'story', 'comment', or 'show_hn'
        """
        query = _trim_query(query, max_keywords=5)
        params = {
            "query": query,
            "tags": search_type,
            "hitsPerPage": max_results,
        }
        try:
            resp = requests.get(
                self.BASE_URL,
                params=params,
                headers=antidetect.random_headers(),
                timeout=DEFAULT_ENGINE_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            results = []
            for hit in data.get("hits", []):
                item_id = hit.get("objectID", "")
                url = f"https://news.ycombinator.com/item?id={item_id}"
                title = (
                    hit.get("title") or hit.get("comment_text", "")[:80] or "HN Comment"
                )
                points = hit.get("points", 0)
                num_comments = hit.get("num_comments", 0)
                snippet = f"{points} pts | {num_comments} comments | by {hit.get('author', '?')}"
                results.append(SearchResult(title=title, url=url, snippet=snippet))
            return results
        except requests.Timeout:
            report("HN search timeout")
            return []
        except Exception as e:
            report(f"HN search error: {e}")
            return []

    def get_thread(self, item_id: str) -> Optional[dict]:
        """Fetch a specific HN thread by item ID."""
        try:
            resp = requests.get(
                f"https://hn.algolia.com/api/v1/items/{item_id}", timeout=10
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            report(f"HN thread fetch error: {e}")
            return None


# ---------------------------------------------------------------------------
# GitHub Search
# ---------------------------------------------------------------------------


class GitHubSearch:
    """
    Search GitHub repos, code, and issues via GitHub Search API.
    Uses GITHUB_TOKEN env var if available (5000 req/hr vs 60 unauth).
    """

    BASE_URL = "https://api.github.com/search"

    def __init__(self):
        self.token = os.environ.get("GITHUB_TOKEN")
        self.extra_headers = {"Accept": "application/vnd.github+json"}
        if self.token:
            self.extra_headers["Authorization"] = f"Bearer {self.token}"

    def search(
        self, query: str, max_results: int = 5, kind: str = "repositories"
    ) -> list[SearchResult]:
        """
        Search GitHub.

        Args:
            query: Search query
            max_results: Max results
            kind: 'repositories', 'code', 'issues', 'commits'
        """
        query = _trim_query(query, max_keywords=4)
        try:
            merged_headers = antidetect.random_headers()
            merged_headers.update(self.extra_headers)
            resp = requests.get(
                f"{self.BASE_URL}/{kind}",
                params={"q": query, "per_page": max_results},
                headers=merged_headers,
                timeout=DEFAULT_ENGINE_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            results = []
            for item in data.get("items", []):
                if kind == "repositories":
                    title = item.get("full_name", "")
                    url = item.get("html_url", "")
                    stars = item.get("stargazers_count", 0)
                    desc = item.get("description") or ""
                    snippet = f"⭐ {stars} | {desc}"
                elif kind == "issues":
                    title = item.get("title", "")
                    url = item.get("html_url", "")
                    state = item.get("state", "")
                    snippet = f"[{state}] {item.get('body', '')[:120]}"
                else:
                    title = (
                        item.get("name") or item.get("path") or item.get("sha", "")[:8]
                    )
                    url = item.get("html_url", "")
                    snippet = item.get("repository", {}).get("full_name", "")
                results.append(SearchResult(title=title, url=url, snippet=snippet))
            return results
        except Exception as e:
            report(f"GitHub search error: {e}")
            return []


# ---------------------------------------------------------------------------
# arXiv
# ---------------------------------------------------------------------------


class ArxivSearch:
    """
    Search arXiv for academic papers.
    No auth required. Free, unlimited.

    Use for: finding research papers, preprints, academic work.
    """

    BASE_URL = "https://export.arxiv.org/api/query"
    NS = "{http://www.w3.org/2005/Atom}"

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Search arXiv papers."""
        try:
            params = {
                "search_query": f"all:{query}",
                "start": 0,
                "max_results": max_results,
                "sortBy": "relevance",
                "sortOrder": "descending",
            }
            resp = requests.get(
                self.BASE_URL,
                params=params,
                headers=antidetect.random_headers(),
                timeout=DEFAULT_ENGINE_TIMEOUT,
            )
            resp.raise_for_status()

            root = ET.fromstring(resp.content)
            results = []
            for entry in root.findall(f"{self.NS}entry"):
                title_el = entry.find(f"{self.NS}title")
                summary_el = entry.find(f"{self.NS}summary")
                id_el = entry.find(f"{self.NS}id")
                title = title_el.text.strip() if title_el is not None else ""
                summary = (
                    summary_el.text.strip()[:200] if summary_el is not None else ""
                )
                url = id_el.text.strip() if id_el is not None else ""
                # Convert API URL to abstract page URL
                url = url.replace("http://arxiv.org/abs/", "https://arxiv.org/abs/")
                results.append(SearchResult(title=title, url=url, snippet=summary))
            return results
        except Exception as e:
            report(f"arXiv search error: {e}")
            return []


# ---------------------------------------------------------------------------
# Semantic Scholar
# ---------------------------------------------------------------------------


class SemanticScholarSearch:
    """
    Search academic papers via Semantic Scholar API.
    No auth required. Covers arXiv, ACL, NeurIPS, ICML, PubMed, and more.
    Better than Google Scholar for programmatic access.

    Use for: finding citations, related work, author profiles.
    """

    BASE_URL = "https://api.semanticscholar.org/graph/v1/paper/search"

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Search Semantic Scholar papers."""
        try:
            params = {
                "query": query,
                "limit": max_results,
                "fields": "title,abstract,url,year,citationCount,authors",
            }
            resp = requests.get(
                self.BASE_URL,
                params=params,
                headers=antidetect.random_headers(),
                timeout=DEFAULT_ENGINE_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            results = []
            for paper in data.get("data", []):
                title = paper.get("title", "")
                url = (
                    paper.get("url")
                    or f"https://www.semanticscholar.org/paper/{paper.get('paperId', '')}"
                )
                year = paper.get("year", "")
                citations = paper.get("citationCount", 0)
                authors = ", ".join(a["name"] for a in paper.get("authors", [])[:3])
                abstract = (paper.get("abstract") or "")[:150]
                snippet = f"{year} | {citations} citations | {authors} | {abstract}"
                results.append(SearchResult(title=title, url=url, snippet=snippet))
            return results
        except Exception as e:
            report(f"Semantic Scholar search error: {e}")
            return []


# ---------------------------------------------------------------------------
# Twitter / X (via ddgs site-scoped search)
# ---------------------------------------------------------------------------


class TwitterSearch:
    """
    Search Twitter/X posts via ddgs site-scoped search (site:x.com).
    No auth required. No API key. Uses the existing ddgs dependency.

    Use for: finding tweets, discussions, opinions, announcements on Twitter/X.
    """

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """
        Search Twitter/X posts.

        Args:
            query: Search query
            max_results: Max results to return
        """
        import re
        from ddgs import DDGS
        from .search import ENGINE_TIMEOUT

        try:
            ddgs = DDGS(timeout=ENGINE_TIMEOUT)
            site_query = f"site:x.com {query}"
            raw_results = list(ddgs.text(site_query, max_results=max_results + 5))

            results = []
            for item in raw_results:
                url = item.get("href", "")
                # Filter to actual tweet/post URLs (skip trending, help, transparency pages)
                if not re.search(r"x\.com/\w+/status/\d+", url):
                    continue
                title = item.get("title", "")
                snippet = item.get("body", "")
                # Extract author handle from URL: x.com/<handle>/status/<id>
                match = re.search(r"x\.com/(\w+)/status/", url)
                author = f"@{match.group(1)}" if match else ""
                if author:
                    snippet = f"{author}: {snippet}"
                results.append(SearchResult(title=title, url=url, snippet=snippet))
                if len(results) >= max_results:
                    break

            return results
        except Exception as e:
            report(f"Twitter/X search error: {e}")
            return []


# ---------------------------------------------------------------------------
# SearXNG (self-hosted meta-search)
# ---------------------------------------------------------------------------


class SearXNGSearch:
    """
    Search via a self-hosted SearXNG instance.
    Queries DDG + Google + Bing + others simultaneously.

    Requires a running SearXNG instance. Set SEARXNG_URL env var or pass url param.
    Default: http://localhost:8888

    To run locally:
        docker run -d -p 8888:8080 searxng/searxng
    """

    def __init__(self, url: Optional[str] = None):
        self.url = url or os.environ.get("SEARXNG_URL", "http://localhost:8888")

    def is_available(self) -> bool:
        """Check if SearXNG instance is reachable."""
        try:
            resp = requests.get(f"{self.url}/healthz", timeout=3)
            return resp.status_code == 200
        except Exception:
            return False

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Search via SearXNG."""
        try:
            params = {
                "q": query,
                "format": "json",
                "categories": "general",
            }
            resp = requests.get(
                f"{self.url}/search", params=params, timeout=DEFAULT_ENGINE_TIMEOUT
            )
            resp.raise_for_status()
            data = resp.json()
            results = []
            for item in data.get("results", [])[:max_results]:
                title = item.get("title", "")
                url = item.get("url", "")
                snippet = item.get("content", "")
                results.append(SearchResult(title=title, url=url, snippet=snippet))
            return results
        except Exception as e:
            report(f"SearXNG search error: {e}")
            return []


# ---------------------------------------------------------------------------
# Marginalia (independent index focused on text-heavy / non-commercial content)
# ---------------------------------------------------------------------------


class MarginaliaSearch:
    """
    Search via Marginalia's free public API.
    No auth required. The "public" API key is rate-limited but free for casual use.
    Marginalia indexes the small/old/text-heavy web missed by mainstream engines.

    Use for: long-tail content, blogs, small-site discovery, surfacing diversity.
    """

    BASE_URL = "https://api.marginalia.nu/public/search"

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        try:
            headers = antidetect.random_headers()
            headers["Accept"] = "application/json"
            resp = requests.get(
                f"{self.BASE_URL}/{requests.utils.quote(query)}",
                params={"count": max_results},
                headers=headers,
                timeout=DEFAULT_ENGINE_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            results = []
            for item in data.get("results", [])[:max_results]:
                title = item.get("title", "") or item.get("url", "")
                url = item.get("url", "")
                snippet = item.get("description", "") or ""
                if url:
                    results.append(SearchResult(title=title, url=url, snippet=snippet))
            return results
        except Exception as e:
            report(f"Marginalia search error: {e}")
            return []


# ---------------------------------------------------------------------------
# Wiby (small-web search engine)
# ---------------------------------------------------------------------------


class WibySearch:
    """
    Search via Wiby's free JSON API.
    No auth required. Indexes hand-curated small web pages — useful for
    finding personal sites, hobby pages, and content not optimized for SEO.

    Use for: small-web discovery, hobby/community sites, eclectic content.
    """

    BASE_URL = "https://wiby.me/json/"

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        try:
            headers = antidetect.random_headers()
            headers["Accept"] = "application/json"
            resp = requests.get(
                self.BASE_URL,
                params={"q": query},
                headers=headers,
                timeout=DEFAULT_ENGINE_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            # Wiby returns a list of {URL, Title, Snippet}
            entries = data if isinstance(data, list) else data.get("results", [])
            results = []
            for item in entries[:max_results]:
                url = item.get("URL") or item.get("url", "")
                title = item.get("Title") or item.get("title", "") or url
                snippet = item.get("Snippet") or item.get("snippet", "")
                if url:
                    results.append(SearchResult(title=title, url=url, snippet=snippet))
            return results
        except Exception as e:
            report(f"Wiby search error: {e}")
            return []


# ---------------------------------------------------------------------------
# Qwant (French meta / privacy search — public JSON endpoint)
# ---------------------------------------------------------------------------


class QwantSearch:
    """
    Search via Qwant's public JSON endpoint.
    No auth. No API key. Rate-limited but free for casual use.

    Qwant's ``/v3/search/web`` returns JSON with ``data.result.items.mainline``
    grouped by type. We flatten ``type == "web"`` groups.
    """

    BASE_URL = "https://api.qwant.com/v3/search/web"

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        try:
            headers = antidetect.random_headers()
            headers["Accept"] = "application/json"
            resp = requests.get(
                self.BASE_URL,
                params={
                    "q": query,
                    "count": max_results,
                    "locale": "en_US",
                    "safesearch": 0,
                },
                headers=headers,
                timeout=DEFAULT_ENGINE_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            mainline = (
                data.get("data", {})
                .get("result", {})
                .get("items", {})
                .get("mainline", [])
            )
            results: list[SearchResult] = []
            for group in mainline:
                if group.get("type") != "web":
                    continue
                for item in group.get("items", [])[:max_results]:
                    url = item.get("url", "")
                    title = item.get("title", "") or url
                    snippet = item.get("desc", "") or ""
                    if url:
                        results.append(
                            SearchResult(title=title, url=url, snippet=snippet)
                        )
                if len(results) >= max_results:
                    break
            return results[:max_results]
        except Exception as e:
            report(f"Qwant search error: {e}")
            return []


# ---------------------------------------------------------------------------
# Ecosia (Bing-powered, HTML-scraped)
# ---------------------------------------------------------------------------


class EcosiaSearch:
    """
    Search via Ecosia's HTML page. Backed by Bing.
    No auth, but we scrape the rendered result list with lxml.

    Parsing is deliberately lenient — each candidate ``<article>`` or ``.result``
    block can change over time. Missing selectors return [] rather than crash.
    """

    BASE_URL = "https://www.ecosia.org/search"

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        try:
            resp = antidetect.request_with_retry(
                self.BASE_URL,
                params={"q": query},
                timeout=DEFAULT_ENGINE_TIMEOUT,
            )
            resp.raise_for_status()
            return _parse_ecosia_html(resp.text, max_results=max_results)
        except Exception as e:
            report(f"Ecosia search error: {e}")
            return []


def _parse_ecosia_html(html_text: str, max_results: int = 5) -> list[SearchResult]:
    """Extract (title, url, snippet) triples from an Ecosia SERP.

    Defensive: Ecosia's markup evolves. We look for any anchor that has a
    plausible result-wrapper ancestor and falls back to any external href.
    Factored out so tests can feed fixture HTML directly.
    """
    from lxml import html as lxml_html

    try:
        tree = lxml_html.fromstring(html_text)
    except Exception:
        return []

    results: list[SearchResult] = []
    seen: set[str] = set()
    # Prefer the structured result containers; fall back to any main-content anchor.
    candidates = tree.xpath(
        "//article[.//a[@data-test-id='result-link']] | //div[contains(@class,'result__body')]"
    )
    if not candidates:
        candidates = tree.xpath("//main//a[starts-with(@href,'http')]/ancestor::*[1]")

    for node in candidates:
        link = node.xpath(".//a[@data-test-id='result-link'][1]")
        if not link:
            link = node.xpath(".//a[starts-with(@href,'http')][1]")
        if not link:
            continue
        url = link[0].get("href") or ""
        if not url or url in seen or url.startswith("https://www.ecosia.org"):
            continue
        title_texts = link[0].xpath(".//text()") or [link[0].text_content()]
        title = "".join(t.strip() for t in title_texts if t and t.strip()).strip()
        if not title:
            title = url
        snippet_nodes = node.xpath(
            ".//*[contains(@class,'result__description') or contains(@class,'snippet')]//text()"
        )
        snippet = " ".join(t.strip() for t in snippet_nodes if t.strip())[:300]
        seen.add(url)
        results.append(SearchResult(title=title, url=url, snippet=snippet))
        if len(results) >= max_results:
            break
    return results


# ---------------------------------------------------------------------------
# Startpage (Google-powered, HTML-scraped)
# ---------------------------------------------------------------------------


class StartpageSearch:
    """
    Search via Startpage's HTML results page. Backed by Google.
    No API key. Startpage is aggressive about bot detection — we rely on the
    antidetect header pool + retry-on-throttle. Expect occasional 403s.
    """

    BASE_URL = "https://www.startpage.com/do/search"

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        try:
            resp = antidetect.request_with_retry(
                self.BASE_URL,
                params={"query": query, "cat": "web", "pl": "opensearch"},
                headers={"Referer": "https://www.startpage.com/"},
                timeout=DEFAULT_ENGINE_TIMEOUT,
            )
            resp.raise_for_status()
            return _parse_startpage_html(resp.text, max_results=max_results)
        except Exception as e:
            report(f"Startpage search error: {e}")
            return []


def _parse_startpage_html(html_text: str, max_results: int = 5) -> list[SearchResult]:
    """Extract results from a Startpage SERP. Factored out for testability."""
    from lxml import html as lxml_html

    try:
        tree = lxml_html.fromstring(html_text)
    except Exception:
        return []

    results: list[SearchResult] = []
    seen: set[str] = set()
    # Startpage wraps results in .w-gl__result or similar.
    containers = tree.xpath(
        "//div[contains(@class,'w-gl__result') or contains(@class,'result')][.//a]"
    )
    for node in containers:
        link = node.xpath(
            ".//a[contains(@class,'w-gl__result-url') or contains(@class,'result-link')][1]"
        )
        if not link:
            link = node.xpath(".//h3/a[1] | .//a[starts-with(@href,'http')][1]")
        if not link:
            continue
        url = link[0].get("href") or ""
        if not url or url in seen:
            continue
        if url.startswith("/"):
            continue
        title = (link[0].text_content() or "").strip() or url
        snippet_nodes = node.xpath(
            ".//*[contains(@class,'description') or contains(@class,'snippet')]//text()"
        )
        snippet = " ".join(t.strip() for t in snippet_nodes if t.strip())[:300]
        seen.add(url)
        results.append(SearchResult(title=title, url=url, snippet=snippet))
        if len(results) >= max_results:
            break
    return results


# ---------------------------------------------------------------------------
# Convenience: multi-source search
# ---------------------------------------------------------------------------


def _ext_result_adapter(inner_cls):
    """Wrap a ``sources_ext`` connector (search → list[dict]) as a SuperSearch
    source (search → list[SearchResult]).

    v0.10 round-3 connectors (EurLex, Lexology, GitHubDeep, OpenCorporates,
    SECEdgar) were built against a minimal dict contract and don't depend on
    supersearch internals. This adapter is the integration seam.
    """

    class _Adapted:
        def __init__(self):
            self._inner = inner_cls()

        def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
            try:
                raw = self._inner.search(query, max_results=max_results) or []
            except Exception as exc:  # noqa: BLE001 — parity with sibling sources
                report(f"{inner_cls.__name__} search error: {exc}")
                return []
            out: list[SearchResult] = []
            for item in raw[:max_results]:
                if not isinstance(item, dict):
                    continue
                url = item.get("url", "") or ""
                if not url:
                    continue
                out.append(
                    SearchResult(
                        title=item.get("title", "") or url,
                        url=url,
                        snippet=item.get("snippet", "") or "",
                    )
                )
            return out

    _Adapted.__name__ = f"{inner_cls.__name__}Adapter"
    return _Adapted


def _source_map():
    """Return the canonical source name -> class mapping."""
    from .search import DuckDuckGoSearch
    from .sources_ext import (
        EurLexSource,
        LexologySource,
        SSRNSource,
        GitHubDeepSource,
        OpenCorporatesSource,
        SECEdgarSource,
    )

    return {
        "ddg": DuckDuckGoSearch,
        "hn": HackerNewsSearch,
        "github": GitHubSearch,
        "arxiv": ArxivSearch,
        "semantic_scholar": SemanticScholarSearch,
        "twitter": TwitterSearch,
        "x": TwitterSearch,
        "searxng": SearXNGSearch,
        "marginalia": MarginaliaSearch,
        "wiby": WibySearch,
        "qwant": QwantSearch,
        "ecosia": EcosiaSearch,
        "startpage": StartpageSearch,
        # v0.10 round-3 connectors (reach-gap closers)
        "eurlex": _ext_result_adapter(EurLexSource),
        "lexology": _ext_result_adapter(LexologySource),
        "ssrn": _ext_result_adapter(SSRNSource),
        "github_deep": _ext_result_adapter(GitHubDeepSource),
        "opencorp": _ext_result_adapter(OpenCorporatesSource),
        "edgar": _ext_result_adapter(SECEdgarSource),
    }


def _run_one_source(
    source_name: str,
    cls,
    query: str,
    max_per_source: int,
    jitter_max: float = 0.0,
) -> tuple[list, list[str]]:
    """Instantiate a source and run search. Swallow exceptions — they must not
    kill sibling sources in the parallel pool.

    ``jitter_max`` adds a random delay (0..jitter_max seconds) before the
    request to desynchronize parallel engine hits. Default 0 keeps tests
    deterministic; ``search_all`` opts in.
    """
    with capture_diagnostics() as diagnostics:
        try:
            if jitter_max > 0:
                antidetect.jitter(0.0, jitter_max)
            searcher = cls()
            results = searcher.search(query, max_results=max_per_source) or []
        except Exception as e:
            report(f"Error from {source_name}: {e}")
            results = []
    return results, diagnostics


def _apply_rerank(query: str, results: list) -> list:
    """Re-rank ``results`` via :class:`LocalReranker`, setting ``SearchResult.score``.

    Returns the results ordered by descending composite relevance score, with
    each result's ``.score`` populated. The reranker uses local Ollama
    embeddings for the semantic signal; without Ollama it degrades to freshness
    + domain-authority scoring. Never raises — on any failure the input list is
    returned unchanged (scores left as ``None``).
    """
    if not results:
        return results
    try:
        from .rerank import LocalReranker

        ranked = LocalReranker().rerank(query, results)
    except Exception as e:
        report(f"Rerank failed, returning unranked results: {e}")
        return results
    out: list = []
    for r, score in ranked:
        try:
            r.score = score
        except Exception:
            pass
        out.append(r)
    return out


def search_all(
    query: str,
    sources: list[str] = None,
    max_per_source: int = 3,
    parallel: bool = True,
    overall_timeout: float = DEFAULT_PARALLEL_TIMEOUT,
    jitter_max: float = 0.0,
    rerank: bool = False,
    diagnostics: list[str] | None = None,
    source_statuses: list[dict] | None = None,
) -> list[SearchResult]:
    """
    Search multiple sources and return combined results.

    Args:
        query: Search query
        sources: List of source names. Defaults to ['ddg', 'hn', 'github', 'twitter']
        max_per_source: Max results per source
        parallel: Run sources concurrently on daemon threads (default True).
            Set False only for deterministic tests.
        overall_timeout: Max wall-clock seconds to wait for ALL sources combined.
            Sources that miss this deadline are skipped; others still return.
        jitter_max: Max random delay (seconds) before each engine call. 0 = no jitter.
        rerank: When True, re-rank the combined results with the local embedding
            re-ranker and populate each ``SearchResult.score``; results come back
            ordered by descending relevance. Default False keeps the output
            byte-identical to prior behaviour (retrieval order, ``score=None``).
            Requires Ollama for the semantic signal; degrades gracefully without.
        diagnostics: Optional caller-owned list populated with source failures
            and timeouts. Normal empty-result searches leave it unchanged.
        source_statuses: Optional caller-owned list populated with one structured
            completion record per requested source. This is the stable seam used
            by the Product V1 receipt; existing callers can ignore it.

    Returns:
        Combined list of SearchResult objects, deduped by URL with provenance
        (each result carries `sources=[engine_names_that_returned_it]`) and
        snippet stitching across engines. With ``rerank=True`` the list is
        ordered by descending ``.score``.
    """
    if sources is None:
        sources = ["ddg", "hn", "github", "twitter"]

    requested_sources = list(sources)
    smap = _source_map()
    jobs = [(name, smap[name]) for name in sources if name in smap]
    status_by_name: dict[str, dict] = {
        name: {
            "name": name,
            "status": "unsupported",
            "result_count": 0,
            "diagnostics": ["source name is not registered"],
        }
        for name in requested_sources
        if name not in smap
    }

    def _record_status(name: str, results: list, messages: list[str]) -> None:
        if messages and results:
            status = "degraded"
        elif messages:
            status = "failed"
        else:
            status = "completed"
        status_by_name[name] = {
            "name": name,
            "status": status,
            "result_count": len(results),
            "diagnostics": list(messages),
        }

    def _publish_statuses() -> None:
        if source_statuses is not None:
            source_statuses.extend(
                status_by_name[name]
                for name in requested_sources
                if name in status_by_name
            )

    if not parallel:
        by_source: dict = {}
        for name, cls in jobs:
            results, messages = _run_one_source(
                name, cls, query, max_per_source, jitter_max
            )
            by_source[name] = results
            _record_status(name, results, messages)
            if diagnostics is not None:
                diagnostics.extend(f"{name}: {message}" for message in messages)
        merged = _merge_with_provenance(by_source)
        _publish_statuses()
        return _apply_rerank(query, merged) if rerank else merged

    # Run each source on its own DAEMON thread and collect results through a
    # queue under one hard wall-clock deadline. Daemon threads are the key
    # property: a source that hangs (e.g. a stuck network socket that outlives
    # its own per-request timeout) is abandoned at the deadline and can neither
    # stall this call nor block interpreter exit. A ThreadPoolExecutor cannot
    # give this guarantee — its worker threads are non-daemon and are joined by
    # an atexit handler, so a truly-hung source would hang the whole process.
    by_source: dict = {}
    result_q: "_queue.Queue[tuple[str, list, list[str]]]" = _queue.Queue()

    def _worker(name: str, cls) -> None:
        try:
            res, messages = _run_one_source(
                name, cls, query, max_per_source, jitter_max
            )
        except Exception as e:  # defensive: _run_one_source already swallows
            message = f"Error from {name}: {e}"
            report(message)
            res = []
            messages = [message]
        result_q.put((name, res or [], messages))

    for name, cls in jobs:
        threading.Thread(
            target=_worker, args=(name, cls), name=f"supersearch-{name}", daemon=True
        ).start()

    deadline = time.monotonic() + overall_timeout
    for _ in range(len(jobs)):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            name, res, messages = result_q.get(timeout=remaining)
            by_source[name] = res
            _record_status(name, res, messages)
            if diagnostics is not None:
                diagnostics.extend(f"{name}: {message}" for message in messages)
        except _queue.Empty:
            break

    if len(by_source) < len(jobs):
        missing = [name for name, _cls in jobs if name not in by_source]
        message = (
            f"Parallel source timeout after {overall_timeout}s; "
            f"skipped slow sources: {', '.join(missing)}"
        )
        report(message)
        if diagnostics is not None:
            diagnostics.append(message)
        for name in missing:
            status_by_name[name] = {
                "name": name,
                "status": "timed_out",
                "result_count": 0,
                "diagnostics": [
                    f"missed the {overall_timeout:g}s overall search deadline"
                ],
            }

    # Re-key in caller's source order so output ordering is deterministic.
    ordered = {name: by_source.get(name, []) for name, _cls in jobs}
    merged = _merge_with_provenance(ordered)
    _publish_statuses()
    return _apply_rerank(query, merged) if rerank else merged


def _dedupe_by_url(results: list) -> list:
    """Flat-list URL dedup. Kept for backwards compatibility / external callers.

    For provenance-aware merging across engines, prefer ``_merge_with_provenance``.
    """
    seen = set()
    out = []
    for r in results:
        url = getattr(r, "url", None)
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(r)
    return out


def _merge_with_provenance(by_source: dict) -> list:
    """Merge per-engine result lists, deduping by URL.

    For each unique URL, the merged result records every engine that returned
    it (``result.sources``) and stitches together unique snippets from each
    engine (joined by ``" | "``). Preserves the iteration order of ``by_source``
    — callers should pass an ordered dict if they care about output ordering.
    """
    seen: dict = {}
    order: list = []
    for source_name, results in by_source.items():
        for r in results or []:
            url = getattr(r, "url", None)
            if not url:
                continue
            if url not in seen:
                merged = SearchResult(
                    title=r.title,
                    url=r.url,
                    snippet=r.snippet,
                    raw_content=getattr(r, "raw_content", None),
                    sources=[source_name],
                )
                seen[url] = merged
                order.append(url)
            else:
                existing = seen[url]
                if source_name not in existing.sources:
                    existing.sources.append(source_name)
                new_snip = (r.snippet or "").strip()
                if new_snip and new_snip not in (existing.snippet or ""):
                    existing.snippet = (
                        f"{existing.snippet} | {new_snip}"
                        if existing.snippet
                        else new_snip
                    )
    return [seen[u] for u in order]
