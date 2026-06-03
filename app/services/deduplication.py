from __future__ import annotations
import time
from collections import OrderedDict
from threading import Lock


class DeduplicationCache:
    """
    Thread-safe LRU cache for event deduplication.
    Stores event_id -> timestamp of processing.
    """

    def __init__(self, max_size: int = 10000, ttl_seconds: int = 3600):
        self._cache: OrderedDict[str, float] = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._lock = Lock()

    def is_duplicate(self, event_id: str) -> bool:
        """Return True if we have seen this event_id recently."""
        with self._lock:
            self._evict_expired()
            return event_id in self._cache

    def mark_seen(self, event_id: str) -> None:
        """Mark event_id as processed."""
        with self._lock:
            self._evict_expired()
            if event_id in self._cache:
                self._cache.move_to_end(event_id)
            else:
                self._cache[event_id] = time.monotonic()
                if len(self._cache) > self._max_size:
                    self._cache.popitem(last=False)

    def _evict_expired(self) -> None:
        now = time.monotonic()
        to_delete = [
            k for k, t in self._cache.items()
            if now - t > self._ttl
        ]
        for k in to_delete:
            del self._cache[k]

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)


# Module-level singleton
_cache: DeduplicationCache | None = None


def get_dedup_cache() -> DeduplicationCache:
    global _cache
    if _cache is None:
        from app.config import get_settings
        s = get_settings()
        _cache = DeduplicationCache(
            max_size=s.DEDUP_CACHE_SIZE,
            ttl_seconds=s.DEDUP_CACHE_TTL_SECONDS,
        )
    return _cache
