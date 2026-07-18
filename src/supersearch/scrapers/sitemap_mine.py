"""
Sitemap + robots.txt miner.

Extracts every URL a site admits it has. Combines two signals:

- robots.txt: parsed for Sitemap: directives AND Disallow: paths. A
  Disallow is a hint that something interesting lives there — staging
  environments, admin panels, internal search handlers, crawl traps.
- sitemap.xml (and nested sitemap indexes): parsed for <loc> URLs. This
  is the site's own declaration of every page it wants indexed, which
  often exceeds what search engines actually show.

Together these surface URLs that don't appear in search results:
deprecated pages, personalized-URL endpoints, per-region variants,
sitemap-only landing pages built for ads.

Usage:
    python3 -m supersearch.scrapers.sitemap_mine example.com
    python3 -m supersearch.scrapers.sitemap_mine https://example.com --limit=500
"""

import gzip
import json
import re
import sys
import xml.etree.ElementTree as ET
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests


DEFAULT_TIMEOUT = 15
DEFAULT_LIMIT = 1000
COMMON_SITEMAP_PATHS = [
    "/sitemap.xml",
    "/sitemap_index.xml",
    "/sitemap-index.xml",
    "/sitemap/sitemap.xml",
    "/wp-sitemap.xml",
]

# Namespace-agnostic <loc> matcher for weird sitemap variants.
LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.IGNORECASE)


def _normalize_origin(domain_or_url: str) -> str:
    s = domain_or_url.strip()
    if s.startswith(("http://", "https://")):
        p = urlparse(s)
        return f"{p.scheme}://{p.netloc}"
    return f"https://{s.rstrip('/')}"


def _get(url: str, timeout: int) -> Optional[requests.Response]:
    try:
        r = requests.get(url, timeout=timeout,
                         headers={"User-Agent": "SuperSearch-SitemapMiner/1.0"},
                         allow_redirects=True)
        if r.status_code == 200 and r.content:
            return r
    except requests.RequestException:  # noqa: silent — best-effort probe; caller handles None
        pass
    return None


def _decompress_if_needed(resp: requests.Response) -> bytes:
    content = resp.content
    if resp.url.endswith(".gz") or content[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(content)
        except OSError:
            return content
    return content


def _parse_sitemap(text: bytes, limit: int, seen: set, urls: list, nested: list) -> None:
    """Append URLs from a sitemap to `urls` (up to limit). Nested sitemaps go to `nested`."""
    # Try XML parse first; fall back to regex for broken XML.
    try:
        root = ET.fromstring(text)
        tag = root.tag.lower()
        # Strip namespace for comparison
        tag_local = tag.split("}", 1)[-1]
        if "sitemapindex" in tag_local:
            for sm in root.iter():
                local = sm.tag.split("}", 1)[-1].lower()
                if local == "loc" and sm.text:
                    loc = sm.text.strip()
                    if loc and loc not in seen:
                        nested.append(loc)
            return
        # urlset
        for loc_el in root.iter():
            local = loc_el.tag.split("}", 1)[-1].lower()
            if local == "loc" and loc_el.text:
                u = loc_el.text.strip()
                if u and u not in seen and len(urls) < limit:
                    seen.add(u)
                    urls.append(u)
        return
    except ET.ParseError:  # noqa: silent — fallback to regex below
        pass
    # Regex fallback — also handles raw <loc> lines in plaintext sitemaps.
    try:
        decoded = text.decode("utf-8", errors="replace")
    except Exception:
        decoded = ""
    for m in LOC_RE.finditer(decoded):
        u = m.group(1).strip()
        if not u or u in seen:
            continue
        # Heuristic: nested sitemaps tend to end in .xml or .xml.gz
        if u.endswith((".xml", ".xml.gz")):
            nested.append(u)
        else:
            if len(urls) < limit:
                seen.add(u)
                urls.append(u)


def _parse_robots(text: str, origin: str) -> dict:
    """Pull Sitemap: and Disallow: from robots.txt."""
    sitemaps: list = []
    disallows: list = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip().lower()
        val = val.strip()
        if key == "sitemap" and val:
            sitemaps.append(val)
        elif key == "disallow" and val and val != "/":
            # Skip bare "/" disallows (they tell us nothing specific).
            full = urljoin(origin + "/", val) if val.startswith("/") else val
            disallows.append(full)
    # Dedupe while preserving order
    return {
        "sitemaps": list(dict.fromkeys(sitemaps)),
        "disallowed_paths": list(dict.fromkeys(disallows)),
    }


def fetch(domain_or_url: str, limit: int = DEFAULT_LIMIT, timeout: int = DEFAULT_TIMEOUT) -> dict:
    origin = _normalize_origin(domain_or_url)
    out = {
        "domain": urlparse(origin).netloc,
        "origin": origin,
        "robots": {"sitemaps": [], "disallowed_paths": []},
        "sitemaps_fetched": [],
        "urls": [],
        "count": 0,
    }

    # 1. Fetch robots.txt
    robots_resp = _get(f"{origin}/robots.txt", timeout)
    if robots_resp is not None:
        try:
            out["robots"] = _parse_robots(robots_resp.text, origin)
        except Exception as e:
            out["robots_error"] = str(e)

    # 2. Collect candidate sitemap URLs — from robots first, then common paths.
    candidates: list = list(out["robots"]["sitemaps"])
    for p in COMMON_SITEMAP_PATHS:
        candidates.append(f"{origin}{p}")
    # Dedupe while preserving order
    candidates = list(dict.fromkeys(candidates))

    # 3. Walk sitemaps (one level of nesting is enough in practice).
    seen_urls: set = set()
    urls: list = []
    to_fetch = candidates[:]
    fetched: set = set()
    MAX_SITEMAPS = 20  # cap to avoid walking huge nested indexes forever
    while to_fetch and len(fetched) < MAX_SITEMAPS and len(urls) < limit:
        sm_url = to_fetch.pop(0)
        if sm_url in fetched:
            continue
        fetched.add(sm_url)
        resp = _get(sm_url, timeout)
        if resp is None:
            continue
        out["sitemaps_fetched"].append(sm_url)
        body = _decompress_if_needed(resp)
        nested: list = []
        _parse_sitemap(body, limit, seen_urls, urls, nested)
        for n in nested:
            if n not in fetched and n not in to_fetch:
                to_fetch.append(n)

    out["urls"] = urls
    out["count"] = len(urls)
    # Light categorization to make the output scannable.
    out["sample_paths"] = sorted({urlparse(u).path.rsplit("/", 1)[0] or "/" for u in urls})[:30]
    return out


def main(argv: Optional[list] = None) -> int:
    argv = argv if argv is not None else sys.argv
    if len(argv) < 2:
        print("Usage: python -m supersearch.scrapers.sitemap_mine <domain_or_url> [--limit=N]")
        return 1
    limit = DEFAULT_LIMIT
    for a in argv[2:]:
        if a.startswith("--limit="):
            try:
                limit = int(a.split("=", 1)[1])
            except ValueError:  # noqa: silent — keep default limit on bad input
                pass
    result = fetch(argv[1], limit=limit)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
