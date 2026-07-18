"""
Certificate Transparency subdomain enumerator (crt.sh).

Queries crt.sh — the public CT log search — for every TLS cert ever issued
for a domain. Returns the deduplicated set of subdomains that ever had a
cert, including subdomains no search engine indexes (dev-*, staging-*,
internal-*, admin-*). This is the standard recon move for finding hidden
infrastructure that the owner never meant to make public.

Free. No auth. Single HTTP call against crt.sh's JSON endpoint.

Usage:
    python3 -m supersearch.scrapers.crt_sh example.com
    python3 -m supersearch.scrapers.crt_sh example.com --include-wildcards
"""

import json
import sys
from typing import Optional

import requests


CRT_SH_URL = "https://crt.sh/"
CERTSPOTTER_URL = "https://api.certspotter.com/v1/issuances"
DEFAULT_TIMEOUT = 30  # crt.sh is often slow; it scans a huge log


def _from_crt_sh(domain: str, timeout: int) -> tuple[set, Optional[str]]:
    """Query crt.sh. Returns (name_set, error_or_None)."""
    names: set = set()
    try:
        resp = requests.get(
            CRT_SH_URL,
            params={"q": f"%.{domain}", "output": "json"},
            timeout=timeout,
            headers={"User-Agent": "SuperSearch-CTLogs/1.0"},
        )
        resp.raise_for_status()
        for entry in resp.json():
            for name in entry.get("name_value", "").splitlines():
                names.add(name.strip().lower())
        return names, None
    except requests.RequestException as e:
        return names, f"crt.sh: {e}"
    except ValueError as e:
        return names, f"crt.sh json: {e}"


def _from_certspotter(domain: str, timeout: int) -> tuple[set, Optional[str]]:
    """Query Certspotter's free issuances endpoint. Complements crt.sh."""
    names: set = set()
    try:
        resp = requests.get(
            CERTSPOTTER_URL,
            params={
                "domain": domain,
                "include_subdomains": "true",
                "expand": "dns_names",
            },
            timeout=timeout,
            headers={"User-Agent": "SuperSearch-CTLogs/1.0"},
        )
        resp.raise_for_status()
        for entry in resp.json():
            for name in entry.get("dns_names", []):
                names.add(str(name).strip().lower())
        return names, None
    except requests.RequestException as e:
        return names, f"certspotter: {e}"
    except ValueError as e:
        return names, f"certspotter json: {e}"


def fetch(domain: str, include_wildcards: bool = False, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Enumerate subdomains of `domain` via CT logs.

    Tries crt.sh first, falls back to Certspotter if crt.sh fails (its
    Postgres-backed web UI is frequently overloaded and returns 502s).
    Returns a dict with the sorted unique subdomain list and a bucketed
    breakdown (apex / dev / staging / admin / api / other).
    """
    domain = domain.strip().lower().lstrip(".")
    if domain.startswith(("http://", "https://")):
        from urllib.parse import urlparse
        domain = urlparse(domain).netloc

    out = {
        "domain": domain,
        "subdomains": [],
        "count": 0,
        "buckets": {},
        "sources_tried": [],
    }

    seen: set = set()
    errors = []
    crt_names, crt_err = _from_crt_sh(domain, timeout)
    out["sources_tried"].append({"source": "crt.sh", "count": len(crt_names), "error": crt_err})
    seen.update(crt_names)
    if crt_err:
        errors.append(crt_err)

    # Always also try Certspotter — different CT log coverage, free.
    cs_names, cs_err = _from_certspotter(domain, timeout)
    out["sources_tried"].append({"source": "certspotter", "count": len(cs_names), "error": cs_err})
    seen.update(cs_names)
    if cs_err:
        errors.append(cs_err)

    if not seen and errors:
        out["error"] = "; ".join(errors)
        return out

    # Post-filter: drop wildcards unless asked, require suffix match on domain.
    filtered = set()
    for name in seen:
        if not name:
            continue
        if name.startswith("*."):
            if not include_wildcards:
                continue
            name = name[2:]
        if not name.endswith(domain):
            continue
        filtered.add(name)
    seen = filtered

    subs = sorted(seen)
    out["subdomains"] = subs
    out["count"] = len(subs)

    buckets = {"apex": [], "dev": [], "staging": [], "admin": [], "api": [], "internal": [], "other": []}
    for s in subs:
        label = s.removesuffix(f".{domain}").removesuffix(domain)
        label = label.rstrip(".")
        if not label:
            buckets["apex"].append(s)
        elif any(k in label for k in ("dev", "test", "qa", "uat")):
            buckets["dev"].append(s)
        elif "stag" in label or "preprod" in label:
            buckets["staging"].append(s)
        elif "admin" in label or "internal" in label or "corp" in label:
            buckets["internal"].append(s)
        elif "api" in label:
            buckets["api"].append(s)
        elif "auth" in label or "login" in label or "sso" in label:
            buckets["admin"].append(s)
        else:
            buckets["other"].append(s)
    out["buckets"] = {k: v for k, v in buckets.items() if v}
    return out


def main(argv: Optional[list] = None) -> int:
    argv = argv if argv is not None else sys.argv
    if len(argv) < 2:
        print("Usage: python -m supersearch.scrapers.crt_sh <domain> [--include-wildcards]")
        return 1
    include_wildcards = "--include-wildcards" in argv
    result = fetch(argv[1], include_wildcards=include_wildcards)
    print(json.dumps(result, indent=2))
    return 0 if "error" not in result else 2


if __name__ == "__main__":
    sys.exit(main())
