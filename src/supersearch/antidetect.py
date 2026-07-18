"""
Anti-detection utilities: User-Agent rotation, header randomization, jitter.

Used by search engines and the page fetcher to look less robotic. Rotation is
deterministic-per-process (random.choice on each call) so failures are easy
to reproduce by seeding `random` in tests.

Conservative defaults: only real browser strings, only headers a real browser
sends, and small jitter windows. Avoid anything that violates terms of service.
"""

from __future__ import annotations

import random
import time
from typing import Optional

# Real browser User-Agent strings (Chrome / Firefox / Safari / Edge across
# Mac / Windows / Linux). Updated 2026-04 — keep current. List MUST be 20+.
USER_AGENTS: tuple[str, ...] = (
    # Chrome — macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    # Chrome — Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    # Chrome — Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    # Firefox — macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.7; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.6; rv:132.0) Gecko/20100101 Firefox/132.0",
    # Firefox — Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
    # Firefox — Linux
    "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0",
    # Safari — macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
    # Edge — Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
    # Mobile Safari — iPhone
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Mobile/15E148 Safari/604.1",
    # Chrome — Android
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; SM-S921B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36",
    # Chrome — older / variety
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
)

ACCEPT_LANGUAGES: tuple[str, ...] = (
    "en-US,en;q=0.9",
    "en-US,en;q=0.8",
    "en-GB,en-US;q=0.9,en;q=0.8",
    "en-US,en;q=0.9,es;q=0.5",
    "en-US,en;q=0.9,fr;q=0.7",
    "en;q=0.9",
)

ACCEPT_ENCODINGS: tuple[str, ...] = (
    "gzip, deflate, br",
    "gzip, deflate, br, zstd",
    "gzip, deflate",
)

ACCEPT_HEADERS: tuple[str, ...] = (
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
)


def random_user_agent() -> str:
    """Return a random real-browser User-Agent string."""
    return random.choice(USER_AGENTS)


def random_headers(referer: Optional[str] = None) -> dict[str, str]:
    """Return a randomized but realistic header set for an HTTP request.

    Args:
        referer: optional Referer header (e.g. a search engine homepage).
            Omitted from the returned dict if None.
    """
    headers = {
        "User-Agent": random_user_agent(),
        "Accept": random.choice(ACCEPT_HEADERS),
        "Accept-Language": random.choice(ACCEPT_LANGUAGES),
        "Accept-Encoding": random.choice(ACCEPT_ENCODINGS),
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none" if referer is None else "cross-site",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def jitter(min_seconds: float = 0.5, max_seconds: float = 2.0) -> None:
    """Sleep a random duration in [min_seconds, max_seconds]. Pass through if min<=0."""
    if min_seconds <= 0 and max_seconds <= 0:
        return
    lo = max(0.0, float(min_seconds))
    hi = max(lo, float(max_seconds))
    time.sleep(random.uniform(lo, hi))


# HTTP status codes that indicate throttling or transient bot blocks.
# On these, the retry helper rotates UA + headers and retries once before
# surfacing the error to the caller.
THROTTLE_STATUS: frozenset[int] = frozenset({429, 403, 503})


def request_with_retry(
    url: str,
    *,
    method: str = "GET",
    params: Optional[dict] = None,
    headers: Optional[dict] = None,
    timeout: float = 10.0,
    max_retries: int = 1,
    **kwargs,
):
    """HTTP request wrapper with UA rotation on throttle.

    - Uses ``random_headers()`` by default (``headers`` override or merge).
    - On 429/403/503, rotates UA + headers and retries up to ``max_retries`` times.
    - Does not retry on network exceptions — callers already handle those.

    Returns the final ``requests.Response`` (may still be a throttled response
    if all retries exhausted). Callers are expected to call ``raise_for_status``
    themselves so this helper stays status-code agnostic.
    """
    import requests  # local import keeps antidetect importable without requests

    attempt = 0
    last_resp = None
    while True:
        req_headers = random_headers()
        if headers:
            req_headers.update(headers)
        last_resp = requests.request(
            method,
            url,
            params=params,
            headers=req_headers,
            timeout=timeout,
            **kwargs,
        )
        if last_resp.status_code not in THROTTLE_STATUS:
            return last_resp
        if attempt >= max_retries:
            return last_resp
        attempt += 1
        # brief jitter between retries so we don't hammer the endpoint
        jitter(0.3, 1.2)
