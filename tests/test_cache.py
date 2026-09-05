"""Tests for the JSON file cache."""

import json
import threading
import time
from pathlib import Path

from supersearch import cache


def test_put_then_get_returns_payload(tmp_cache_dir):
    assert cache.put("ddg", "hello world", {"a": 1}, cache_dir=tmp_cache_dir)
    got = cache.get("ddg", "hello world", cache_dir=tmp_cache_dir)
    assert got == {"a": 1}


def test_get_missing_returns_none(tmp_cache_dir):
    assert cache.get("ddg", "missing query", cache_dir=tmp_cache_dir) is None


def test_environment_can_isolate_default_cache(tmp_path, monkeypatch):
    isolated = tmp_path / "isolated-cache"
    monkeypatch.setenv("SUPERSEARCH_CACHE_DIR", str(isolated))
    assert cache.put("ddg", "isolated", {"ok": True})
    assert cache.get("ddg", "isolated") == {"ok": True}
    assert list(isolated.glob("*.json"))


def test_empty_environment_override_falls_back(monkeypatch):
    monkeypatch.setenv("SUPERSEARCH_CACHE_DIR", "")
    assert cache.default_cache_dir() == cache.DEFAULT_CACHE_DIR


def test_key_is_source_scoped(tmp_cache_dir):
    cache.put("ddg", "q", [1, 2, 3], cache_dir=tmp_cache_dir)
    assert cache.get("hn", "q", cache_dir=tmp_cache_dir) is None


def test_expired_entries_are_rejected(tmp_cache_dir):
    cache.put("ddg", "old", {"x": 1}, cache_dir=tmp_cache_dir)
    # Shouldn't be stale when TTL is huge
    assert cache.get("ddg", "old", ttl_seconds=3600, cache_dir=tmp_cache_dir) == {"x": 1}
    # Ask for 0-second freshness -> treated as cache disabled
    assert cache.get("ddg", "old", ttl_seconds=0, cache_dir=tmp_cache_dir) is None


def test_expired_by_wall_clock(tmp_cache_dir, monkeypatch):
    cache.put("ddg", "t", ["data"], cache_dir=tmp_cache_dir)
    # Jump forward 2 days, should be stale at 1-day TTL
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() + 48 * 3600)
    assert cache.get("ddg", "t", ttl_seconds=86400, cache_dir=tmp_cache_dir) is None


def test_clear_removes_all_entries(tmp_cache_dir):
    cache.put("a", "1", [1], cache_dir=tmp_cache_dir)
    cache.put("a", "2", [2], cache_dir=tmp_cache_dir)
    cache.put("b", "3", [3], cache_dir=tmp_cache_dir)
    removed = cache.clear(cache_dir=tmp_cache_dir)
    assert removed == 3
    assert cache.get("a", "1", cache_dir=tmp_cache_dir) is None


def test_clear_preserves_unrelated_and_forged_json(tmp_cache_dir):
    cache.put("ddg", "owned", {"ok": True}, cache_dir=tmp_cache_dir)
    directory = Path(tmp_cache_dir)
    unrelated = directory / "important.json"
    unrelated.write_text('{"trusted": true}')
    forged = directory / ("a" * 24 + ".json")
    forged.write_text('{"source": "ddg", "query": "not-that-hash"}')

    assert cache.clear(cache_dir=tmp_cache_dir) == 1
    assert unrelated.exists()
    assert forged.exists()


def test_put_survives_unserializable_payload(tmp_cache_dir):
    # Writing a set (not JSON-serializable) should NOT raise, just return False.
    ok = cache.put("x", "q", {1, 2, 3}, cache_dir=tmp_cache_dir)
    assert ok is False


def test_concurrent_put_same_key_both_succeed_without_corruption(tmp_cache_dir, monkeypatch):
    # put() used to give every writer for a key the same .tmp path. Two
    # concurrent writers then raced on one inode: whichever opened second
    # truncated the first's in-progress bytes, and whichever replace() ran
    # second raised (its shared tmp path had already been renamed away by
    # the winner), so one writer returned False and the survivor's file
    # could be a corrupted splice of both payloads.
    #
    # Force the two threads to both be mid-write at the same instant by
    # splitting the json.dump() call around a barrier: neither thread may
    # write its second half until both have opened their tmp file and
    # written their first half, which is exactly the window where a shared
    # tmp path corrupts.
    barrier = threading.Barrier(2)

    def synced_dump(entry, fp):
        text = json.dumps(entry)
        mid = len(text) // 2
        fp.write(text[:mid])
        fp.flush()
        barrier.wait(timeout=5)
        fp.write(text[mid:])

    monkeypatch.setattr(cache.json, "dump", synced_dump)

    payload_a = {"writer": "a", "data": "x" * 200}
    payload_b = {"writer": "b", "data": "y" * 200}
    results = {}

    def worker(name, payload):
        results[name] = cache.put("ddg", "race", payload, cache_dir=tmp_cache_dir)

    t1 = threading.Thread(target=worker, args=("a", payload_a))
    t2 = threading.Thread(target=worker, args=("b", payload_b))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert results == {"a": True, "b": True}
    assert cache.get("ddg", "race", cache_dir=tmp_cache_dir) in (payload_a, payload_b)


def test_get_survives_corrupt_cache_file(tmp_cache_dir, tmp_path):
    key = cache._cache_key("ddg", "corrupt")
    path = cache._cache_path(tmp_cache_dir, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json")
    # Must not raise — corrupt entries degrade to a miss.
    assert cache.get("ddg", "corrupt", cache_dir=tmp_cache_dir) is None
