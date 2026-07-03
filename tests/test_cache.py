"""Tests for :mod:`scientific_reviewer.cache`."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from scientific_reviewer import cache


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolate_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect the cache directory to a temporary path for each test."""
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(cache, "CACHE_FILE", tmp_path / "cache.json")
    # Ensure no leftover file from previous test
    cache_file = tmp_path / "cache.json"
    if cache_file.is_file():
        cache_file.unlink()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCacheGetSet:
    """Basic get / set round-trips."""

    def test_set_and_get(self) -> None:
        cache.set("pmid:123", {"title": "Test Article"})
        val = cache.get("pmid:123")
        assert val == {"title": "Test Article"}

    def test_get_missing_key(self) -> None:
        assert cache.get("nonexistent") is None

    def test_get_after_clear(self) -> None:
        cache.set("key1", "value1")
        cache.clear()
        assert cache.get("key1") is None

    def test_overwrite_existing_key(self) -> None:
        cache.set("k", "old")
        cache.set("k", "new")
        assert cache.get("k") == "new"

    def test_complex_nested_value(self) -> None:
        complex_val = {
            "pmid": "23193287",
            "exists": True,
            "authors": ["Smith JA", "Jones BC"],
            "citations": {"apa": "Smith (2012)...", "bibtex": "@article{...}"},
            "issues": [],
        }
        cache.set("pmid:23193287", complex_val)
        assert cache.get("pmid:23193287") == complex_val


class TestCacheStatus:
    """Cache status reporting."""

    def test_empty_cache(self) -> None:
        st = cache.status()
        assert st["entries"] == 0
        # No file yet, so size is 0
        assert st["size_bytes"] == 0

    def test_empty_cache_after_clear(self) -> None:
        cache.set("a", 1)
        cache.clear()
        st = cache.status()
        assert st["entries"] == 0
        # File still exists but contains just {}
        assert st["size_bytes"] == 2

    def test_non_empty_cache(self) -> None:
        cache.set("a", 1)
        cache.set("b", 2)
        st = cache.status()
        assert st["entries"] == 2
        assert st["size_bytes"] > 0

    def test_after_clear(self) -> None:
        cache.set("a", 1)
        cache.clear()
        st = cache.status()
        assert st["entries"] == 0


class TestCachePersistence:
    """Verify data persists across a reload."""

    def test_write_and_reread(self) -> None:
        cache.set("persist", "stored")
        # Re-read from disk by calling get
        assert cache.get("persist") == "stored"

    def test_cache_dir_created(self) -> None:
        # Remove the dir that _isolate_cache created
        import shutil
        shutil.rmtree(cache.CACHE_DIR)
        cache.set("new", "value")  # should recreate dir
        assert cache.get("new") == "value"


class TestCacheEdgeCases:
    """Edge cases and error handling."""

    def test_get_on_corrupted_file(self) -> None:
        cache.set("ok", "val")
        cache.CACHE_FILE.write_text("{corrupted json")
        # Should recover gracefully
        assert cache.get("ok") is None

    def test_set_large_value(self) -> None:
        large = {"data": "x" * 100_000}
        cache.set("large", large)
        assert cache.get("large") == large

    def test_set_none_value(self) -> None:
        cache.set("null_key", None)
        assert cache.get("null_key") is None

    def test_status_no_file(self) -> None:
        import shutil
        shutil.rmtree(cache.CACHE_DIR)
        st = cache.status()
        assert st["entries"] == 0
        assert st["size_bytes"] == 0

    def test_timestamp_recorded(self) -> None:
        before = time.time()
        cache.set("ts_test", "value")
        after = time.time()
        raw = json.loads(cache.CACHE_FILE.read_text())
        ts = raw["ts_test"]["timestamp"]
        assert before <= ts <= after

    def test_clear_empty_cache(self) -> None:
        # Should not raise
        cache.clear()
        assert cache.status()["entries"] == 0

    def test_get_with_special_chars(self) -> None:
        key = "gene:TP53/ENST.1+"
        val = "p53_protein"
        cache.set(key, val)
        assert cache.get(key) == val


class TestCacheThreadSafety:
    """Basic thread-safety smoke test."""

    def test_concurrent_writes(self) -> None:
        n_threads = 10
        n_writes = 20

        def _writer(thread_id: int) -> None:
            for i in range(n_writes):
                cache.set(f"t{thread_id}_i{i}", thread_id * 1000 + i)

        threads = [threading.Thread(target=_writer, args=(tid,)) for tid in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        st = cache.status()
        assert st["entries"] == n_threads * n_writes
