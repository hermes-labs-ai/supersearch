"""
Simple JSON file cache for SuperSearch results.

Keyed by a hash of (source, query). Entries expire after TTL seconds (default 24h).
Designed to be dependency-free and safe to miss: any exception reading/writing
the cache must degrade to a live lookup, never raise to the caller.
"""

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

DEFAULT_TTL_SECONDS = 24 * 60 * 60  # 24h
DEFAULT_CACHE_DIR = os.path.expanduser("~/.supersearch/cache")


def default_cache_dir() -> str:
    """Return the active cache directory, honoring the isolation override."""

    override = os.environ.get("SUPERSEARCH_CACHE_DIR")
    return override if override and override.strip() else DEFAULT_CACHE_DIR


def _cache_key(source: str, query: str) -> str:
    raw = f"{source}::{query}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


def _cache_path(cache_dir: str, key: str) -> Path:
    return Path(cache_dir) / f"{key}.json"


_CACHE_FILE_NAME = re.compile(r"[0-9a-f]{24}\.json")


def _owned_cache_file(path: Path) -> bool:
    """Return whether ``path`` is an entry written by this cache implementation."""

    if _CACHE_FILE_NAME.fullmatch(path.name) is None:
        return False
    try:
        entry = json.loads(path.read_text())
        source = entry.get("source")
        query = entry.get("query")
        return (
            isinstance(source, str)
            and isinstance(query, str)
            and path.stem == _cache_key(source, query)
        )
    except Exception:
        return False


def get(
    source: str,
    query: str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    cache_dir: Optional[str] = None,
) -> Optional[Any]:
    """Return cached payload for (source, query) if fresh, else None.

    Returns None on any read error or expired entry. Never raises.
    """
    if ttl_seconds <= 0:
        return None
    if cache_dir is None:
        cache_dir = default_cache_dir()
    try:
        path = _cache_path(cache_dir, _cache_key(source, query))
        if not path.exists():
            return None
        with path.open("r") as f:
            entry = json.load(f)
        ts = entry.get("ts", 0)
        if time.time() - ts > ttl_seconds:
            return None
        return entry.get("payload")
    except Exception:
        return None


def put(
    source: str,
    query: str,
    payload: Any,
    cache_dir: Optional[str] = None,
) -> bool:
    """Write payload to cache under (source, query). Returns True on success.

    Silently returns False on error. Never raises.
    """
    if cache_dir is None:
        cache_dir = default_cache_dir()
    try:
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        path = _cache_path(cache_dir, _cache_key(source, query))
        entry = {
            "source": source,
            "query": query,
            "ts": time.time(),
            "payload": payload,
        }
        tmp = path.with_suffix(".tmp")
        with tmp.open("w") as f:
            json.dump(entry, f)
        tmp.replace(path)
        return True
    except Exception:
        return False


def clear(cache_dir: Optional[str] = None) -> int:
    """Delete all cache entries. Returns number of files removed."""
    if cache_dir is None:
        cache_dir = default_cache_dir()
    count = 0
    try:
        p = Path(cache_dir)
        if not p.exists():
            return 0
        for f in p.glob("*.json"):
            if not _owned_cache_file(f):
                continue
            try:
                f.unlink()
                count += 1
            except Exception:
                continue
    except Exception:
        return count
    return count
