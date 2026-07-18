"""
security.txt scraper.

Fetches /.well-known/security.txt for a domain (RFC 9116). Returns structured
disclosure metadata (contacts, expires, policy URLs). Use this to check
whether a target company has a vulnerability-disclosure program and where
to report issues.

Usage:
    python3 -m supersearch.scrapers.security_txt example.com
    python3 -m supersearch.scrapers.security_txt https://example.com
"""

import json
import re
import sys
from typing import Optional
from urllib.parse import urlparse

import requests


DEFAULT_TIMEOUT = 8
WELL_KNOWN_PATH = "/.well-known/security.txt"
LEGACY_PATH = "/security.txt"

# RFC 9116 lists these fields as standard.
STANDARD_FIELDS = {
    "contact",
    "expires",
    "encryption",
    "acknowledgments",
    "preferred-languages",
    "canonical",
    "policy",
    "hiring",
    "csaf",
}


def _normalize(domain_or_url: str) -> str:
    """Return a bare origin like 'https://example.com' from any input form."""
    s = domain_or_url.strip()
    if s.startswith(("http://", "https://")):
        parsed = urlparse(s)
        return f"{parsed.scheme}://{parsed.netloc}"
    return f"https://{s.rstrip('/')}"


def _parse(text: str) -> dict:
    """Parse security.txt content into a dict of lists (multiple values allowed per field)."""
    fields: dict = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z][A-Za-z-]+)\s*:\s*(.+)$", line)
        if not m:
            continue
        key = m.group(1).lower()
        val = m.group(2).strip()
        fields.setdefault(key, []).append(val)
    return fields


def fetch(domain_or_url: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Fetch and parse /.well-known/security.txt. Returns a structured result.

    The result always includes 'domain', 'found' (bool), 'url' (if found),
    and 'fields' (parsed dict). Errors populate 'error' and 'found' stays False.
    """
    origin = _normalize(domain_or_url)
    out = {
        "domain": urlparse(origin).netloc,
        "found": False,
        "url": None,
        "fields": {},
        "standard_fields": [],
        "non_standard_fields": [],
    }
    headers = {"User-Agent": "SuperSearch-SecurityTxt/1.0"}
    for path in (WELL_KNOWN_PATH, LEGACY_PATH):
        url = f"{origin}{path}"
        try:
            resp = requests.get(url, timeout=timeout, headers=headers, allow_redirects=True)
        except requests.RequestException as e:
            out["error"] = f"request failed: {e}"
            continue
        if resp.status_code == 200 and "contact" in resp.text.lower():
            parsed = _parse(resp.text)
            if parsed:
                out["found"] = True
                out["url"] = url
                out["fields"] = parsed
                out["standard_fields"] = sorted(k for k in parsed if k in STANDARD_FIELDS)
                out["non_standard_fields"] = sorted(k for k in parsed if k not in STANDARD_FIELDS)
                out.pop("error", None)
                return out
    return out


def main(argv: Optional[list] = None) -> int:
    argv = argv if argv is not None else sys.argv
    if len(argv) < 2:
        print("Usage: python -m supersearch.scrapers.security_txt <domain>")
        return 1
    result = fetch(argv[1])
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
