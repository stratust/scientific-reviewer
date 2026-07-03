"""Thread-safe persistent JSON cache for the scientific-reviewer package.

Stores cached API results at ``~/.scientific_reviewer/cache.json``.
Each entry contains the cached value and a Unix timestamp of when it
was written.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

CACHE_DIR = Path.home() / ".scientific_reviewer"
CACHE_FILE = CACHE_DIR / "cache.json"

_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ensure_cache_dir() -> None:
    """Create ``~/.scientific_reviewer`` if it does not exist."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _read_raw() -> dict[str, dict[str, Any]]:
    """Return the full cache dict, or an empty dict on any failure."""
    if not CACHE_FILE.is_file():
        return {}
    try:
        raw = CACHE_FILE.read_text(encoding="utf-8")
        return dict(json.loads(raw))
    except (json.JSONDecodeError, OSError, ValueError):
        return {}


def _write_raw(data: dict[str, dict[str, Any]]) -> None:
    """Atomically write *data* to the cache file."""
    _ensure_cache_dir()
    tmp = CACHE_FILE.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp.replace(CACHE_FILE)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get(key: str) -> Any | None:
    """Retrieve a cached value by *key*.

    Returns the stored ``result`` if the key exists, otherwise ``None``.
    This method does **not** check freshness — the caller is responsible
    for any TTL logic.

    Parameters:
        key: Cache lookup key (typically a PMID, gene symbol, etc.).

    Returns:
        The cached result, or ``None`` if the key is absent.
    """
    with _lock:
        store = _read_raw()
    entry = store.get(key)
    if entry is None:
        return None
    return entry.get("result")


def set(key: str, value: Any) -> None:
    """Store *value* under *key* with the current timestamp.

    Parameters:
        key:   Cache key.
        value: Any JSON-serialisable object to cache.
    """
    with _lock:
        store = _read_raw()
        store[key] = {"result": value, "timestamp": time.time()}
        _write_raw(store)


def status() -> dict[str, int]:
    """Return summary statistics about the cache.

    Returns:
        A dict with keys ``entries`` (total cached items) and
        ``size_bytes`` (on-disk file size).
    """
    with _lock:
        store = _read_raw()
    size = CACHE_FILE.stat().st_size if CACHE_FILE.is_file() else 0
    return {"entries": len(store), "size_bytes": size}


def clear() -> None:
    """Remove all entries from the cache."""
    with _lock:
        _write_raw({})
