"""
infra/rss/rss_cache.py — SHA-256 deduplication cache for RSS entries.

Guarantees:
  • Never overwrites history (append-only JSONL)
  • Thread-safe writes via a per-instance lock
  • Works in pure-memory mode or JSONL-backed mode
  • No Orchestrator / Radar dependency
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from typing import Optional


def _entry_hash(entry: dict) -> str:
    """SHA-256 of (link, title, published_at) — the stable identity of an RSS item."""
    key = "|".join([
        entry.get("link", ""),
        entry.get("title", ""),
        entry.get("published_at", ""),
    ])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class RSSCache:
    """
    Deduplication cache for normalized RSS entries.

    Args:
        cache_path: Optional path to a JSONL file for persistent storage.
                    If None, operates in memory-only mode.
        load_existing: If True (default), loads existing hashes from disk at init.
    """

    def __init__(self, cache_path: Optional[str] = None, load_existing: bool = True):
        self._path   = cache_path
        self._hashes: set[str] = set()
        self._lock   = threading.Lock()

        if cache_path and load_existing and os.path.isfile(cache_path):
            self._load(cache_path)

    def _load(self, path: str) -> None:
        """Populate in-memory hash set from existing JSONL cache file."""
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        try:
                            record = json.loads(line)
                            h = record.get("hash")
                            if h:
                                self._hashes.add(h)
                        except (json.JSONDecodeError, AttributeError):
                            pass
        except OSError:
            pass

    def _persist(self, entry_hash: str, entry: dict) -> None:
        """Append a new cache record to JSONL (append-only, never overwrites)."""
        if not self._path:
            return
        record = {
            "hash":       entry_hash,
            "cached_at":  datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "link":       entry.get("link", ""),
            "title":      entry.get("title", ""),
            "source":     entry.get("source", ""),
        }
        try:
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass  # persistence failure is non-fatal; the in-memory set is still updated

    def filter_new(self, entries: list[dict]) -> list[dict]:
        """
        Return only entries not yet seen. Marks seen entries in the cache.
        Thread-safe.
        """
        new_entries: list[dict] = []
        with self._lock:
            for entry in entries:
                h = _entry_hash(entry)
                if h not in self._hashes:
                    self._hashes.add(h)
                    self._persist(h, entry)
                    new_entries.append(entry)
        return new_entries

    @property
    def size(self) -> int:
        """Number of unique hashes currently tracked."""
        with self._lock:
            return len(self._hashes)

    def reset(self) -> None:
        """Clear in-memory cache. Does NOT delete the JSONL file."""
        with self._lock:
            self._hashes.clear()
