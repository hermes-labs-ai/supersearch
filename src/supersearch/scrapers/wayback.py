"""
Wayback Machine scraper (web.archive.org CDX API).

Two modes:

1. History mode (default): given a URL, list every snapshot ever taken,
   deduplicated by content digest so you only see versions where the page
   actually changed. Great for tracking what a company removed, what
   pricing used to be, when a product quietly disappeared.

2. Discovery mode (--discovery): given a domain, list every URL the
   archive has ever seen under that domain. Surfaces pages that were
   deleted from the live site but still exist in history — old blog
   posts, leaked staging pages, deprecated docs.

Free. No auth. Rate-limited politely by CDX.

Usage:
    python3 -m supersearch.scrapers.wayback https://example.com/pricing
    python3 -m supersearch.scrapers.wayback example.com --discovery
    python3 -m supersearch.scrapers.wayback example.com --discovery --limit=50
"""

import json
import sys
from typing import Optional
from urllib.parse import urlparse

import requests


CDX_URL = "https://web.archive.org/cdx/search/cdx"
DEFAULT_TIMEOUT = 30
DEFAULT_LIMIT = 100


def _archive_url(timestamp: str, original: str) -> str:
    return f"https://web.archive.org/web/{timestamp}/{original}"


def fetch_history(url: str, limit: int = DEFAULT_LIMIT, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """List distinct snapshots of `url`, deduplicated by content digest."""
    out = {"url": url, "mode": "history", "snapshots": [], "count": 0}
    params = {
        "url": url,
        "output": "json",
        "collapse": "digest",  # only rows where digest changed — real content changes
        "fl": "timestamp,original,mimetype,statuscode,digest,length",
        "limit": str(limit),
    }
    try:
        resp = requests.get(CDX_URL, params=params, timeout=timeout,
                            headers={"User-Agent": "SuperSearch-Wayback/1.0"})
        resp.raise_for_status()
        rows = resp.json()
    except requests.RequestException as e:
        out["error"] = f"request failed: {e}"
        return out
    except ValueError as e:
        out["error"] = f"json parse failed: {e}"
        return out

    if not rows or len(rows) < 2:
        out["error"] = "no snapshots found"
        return out

    header, *data = rows
    idx = {name: i for i, name in enumerate(header)}
    for row in data:
        ts = row[idx["timestamp"]]
        original = row[idx["original"]]
        snap = {
            "timestamp": ts,
            "human_date": f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}",
            "status": row[idx["statuscode"]],
            "mimetype": row[idx["mimetype"]],
            "length": int(row[idx["length"]]) if row[idx["length"]].isdigit() else None,
            "archive_url": _archive_url(ts, original),
        }
        out["snapshots"].append(snap)
    out["count"] = len(out["snapshots"])
    out["first_seen"] = out["snapshots"][0]["human_date"] if out["snapshots"] else None
    out["last_seen"] = out["snapshots"][-1]["human_date"] if out["snapshots"] else None
    return out


def fetch_discovery(domain: str, limit: int = DEFAULT_LIMIT, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """List every unique URL the archive has under `domain`."""
    domain = domain.strip().lower().lstrip(".")
    if domain.startswith(("http://", "https://")):
        domain = urlparse(domain).netloc
    out = {"domain": domain, "mode": "discovery", "urls": [], "count": 0}
    params = {
        "url": f"{domain}/*",
        "output": "json",
        "collapse": "urlkey",   # dedupe by URL regardless of snapshot
        "fl": "original,timestamp,mimetype,statuscode",
        "filter": "statuscode:200",
        "limit": str(limit),
    }
    try:
        resp = requests.get(CDX_URL, params=params, timeout=timeout,
                            headers={"User-Agent": "SuperSearch-Wayback/1.0"})
        resp.raise_for_status()
        rows = resp.json()
    except requests.RequestException as e:
        out["error"] = f"request failed: {e}"
        return out
    except ValueError as e:
        out["error"] = f"json parse failed: {e}"
        return out

    if not rows or len(rows) < 2:
        out["error"] = "no archived URLs found"
        return out

    header, *data = rows
    idx = {name: i for i, name in enumerate(header)}
    seen = set()
    for row in data:
        original = row[idx["original"]]
        if original in seen:
            continue
        seen.add(original)
        ts = row[idx["timestamp"]]
        out["urls"].append({
            "url": original,
            "last_seen": f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}",
            "mimetype": row[idx["mimetype"]],
            "archive_url": _archive_url(ts, original),
        })
    out["count"] = len(out["urls"])
    return out


def main(argv: Optional[list] = None) -> int:
    argv = argv if argv is not None else sys.argv
    if len(argv) < 2:
        print("Usage: python -m supersearch.scrapers.wayback <url_or_domain> [--discovery] [--limit=N]")
        return 1
    target = argv[1]
    discovery = "--discovery" in argv
    limit = DEFAULT_LIMIT
    for a in argv[2:]:
        if a.startswith("--limit="):
            try:
                limit = int(a.split("=", 1)[1])
            except ValueError:  # noqa: silent — keep default limit on bad input
                pass
    result = fetch_discovery(target, limit=limit) if discovery else fetch_history(target, limit=limit)
    print(json.dumps(result, indent=2))
    return 0 if "error" not in result else 2


if __name__ == "__main__":
    sys.exit(main())
