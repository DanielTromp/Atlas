"""Cache utilities with basic instrumentation and invalidation hooks."""
from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Mapping, MutableMapping
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


@dataclass(slots=True)
class CacheEntry(Generic[V]):
    value: V
    expires_at: float


@dataclass(slots=True)
class CacheMetrics:
    """Simple metric bundle emitted by caches for observability."""

    hits: int = 0
    misses: int = 0
    loads: int = 0
    evictions: int = 0
    created_at: float = field(default_factory=time.monotonic)
    last_refresh: float | None = None

    def snapshot(self) -> CacheMetrics:
        return CacheMetrics(
            hits=self.hits,
            misses=self.misses,
            loads=self.loads,
            evictions=self.evictions,
            created_at=self.created_at,
            last_refresh=self.last_refresh,
        )


@dataclass
class TTLCache(Generic[K, V]):
    """In-memory TTL cache with thread-safe access and instrumentation."""

    ttl_seconds: float
    name: str | None = None
    store: MutableMapping[K, CacheEntry[V]] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)
    _metrics: CacheMetrics = field(default_factory=CacheMetrics, init=False, repr=False)
    _listeners: list[Callable[[K | None], None]] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.name:
            get_cache_registry().register(self)

    def get(self, key: K, loader: Callable[[], V]) -> V:
        now = time.monotonic()
        with self._lock:
            entry = self.store.get(key)
            if entry and entry.expires_at > now:
                self._metrics.hits += 1
                return entry.value
            self._metrics.misses += 1

        value = loader()

        with self._lock:
            self.store[key] = CacheEntry(value=value, expires_at=now + self.ttl_seconds)
            self._metrics.loads += 1
            self._metrics.last_refresh = time.monotonic()
        return value

    def invalidate(self, key: K | None = None) -> None:
        listeners: Iterable[Callable[[K | None], None]]
        removed = 0
        with self._lock:
            if key is None:
                removed = len(self.store)
                self.store.clear()
            else:
                removed = 1 if key in self.store else 0
                self.store.pop(key, None)
            self._metrics.evictions += removed
            listeners = tuple(self._listeners)
        for listener in listeners:
            listener(key)

    def register_invalidation_listener(self, callback: Callable[[K | None], None]) -> None:
        with self._lock:
            self._listeners.append(callback)

    def snapshot_metrics(self) -> CacheMetrics:
        with self._lock:
            return self._metrics.snapshot()

    def size(self) -> int:
        with self._lock:
            return len(self.store)


class CacheRegistry:
    """Registry for cache lookup and coordinated invalidation."""

    def __init__(self) -> None:
        self._caches: dict[str, TTLCache[Any, Any]] = {}
        self._lock = Lock()

    def register(self, cache: TTLCache[Any, Any]) -> None:
        if cache.name is None:
            return
        with self._lock:
            self._caches[cache.name] = cache

    def unregister(self, name: str) -> None:
        with self._lock:
            self._caches.pop(name, None)

    def invalidate(self, name: str | None = None, key: Any | None = None) -> None:
        with self._lock:
            targets: Iterable[TTLCache[Any, Any]]
            if name is None:
                targets = tuple(self._caches.values())
            else:
                cache = self._caches.get(name)
                targets = (cache,) if cache else ()
        for cache in targets:
            cache.invalidate(key)

    def snapshot(self) -> Mapping[str, dict[str, Any]]:
        with self._lock:
            items = list(self._caches.items())
        out: dict[str, dict[str, Any]] = {}
        for name, cache in items:
            if cache is None:
                continue
            out[name] = {
                "metrics": cache.snapshot_metrics(),
                "size": cache.size(),
                "ttl_seconds": cache.ttl_seconds,
            }
        return out

    def list_caches(self) -> Iterable[str]:
        with self._lock:
            return tuple(self._caches.keys())


_GLOBAL_CACHE_REGISTRY = CacheRegistry()


def get_cache_registry() -> CacheRegistry:
    return _GLOBAL_CACHE_REGISTRY


__all__ = ["CacheMetrics", "CacheRegistry", "TTLCache", "get_cache_registry"]
