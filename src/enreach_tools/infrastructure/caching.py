"""Simple TTL cache utilities used by external adapters."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Callable, Generic, MutableMapping, TypeVar

K = TypeVar("K")
V = TypeVar("V")


@dataclass(slots=True)
class CacheEntry(Generic[V]):
    value: V
    expires_at: float


@dataclass
class TTLCache(Generic[K, V]):
    """In-memory TTL cache with thread-safe access.

    This intentionally keeps the implementation straightforward so it can be
    replaced later with redis/memcached without changing adapter signatures.
    """

    ttl_seconds: float
    store: MutableMapping[K, CacheEntry[V]] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def get(self, key: K, loader: Callable[[], V]) -> V:
        now = time.monotonic()
        with self._lock:
            entry = self.store.get(key)
            if entry and entry.expires_at > now:
                return entry.value
        value = loader()
        with self._lock:
            self.store[key] = CacheEntry(value=value, expires_at=now + self.ttl_seconds)
        return value

    def invalidate(self, key: K | None = None) -> None:
        with self._lock:
            if key is None:
                self.store.clear()
            else:
                self.store.pop(key, None)


__all__ = ["TTLCache"]
