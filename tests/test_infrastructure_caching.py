from __future__ import annotations

from typing import Any

from enreach_tools.infrastructure.caching import CacheRegistry, TTLCache, get_cache_registry


def test_ttlcache_loader_called_once_and_metrics_snapshot() -> None:
    calls = {"count": 0}

    def loader() -> int:
        calls["count"] += 1
        return calls["count"]

    cache = TTLCache[int, int](ttl_seconds=60, name="test.cache")
    assert cache.get(1, loader) == 1
    assert cache.get(1, loader) == 1
    cache.invalidate(1)
    assert cache.get(1, loader) == 2

    metrics = cache.snapshot_metrics()
    assert (metrics.hits, metrics.misses, metrics.loads) == (1, 2, 2)
    assert metrics.evictions == 1


def test_ttlcache_invalidation_listener_invoked() -> None:
    triggered: list[Any] = []
    cache = TTLCache[str, str](ttl_seconds=10)
    cache.register_invalidation_listener(triggered.append)
    cache.invalidate("foo")
    cache.invalidate()
    assert triggered == ["foo", None]


def test_cache_registry_invalidate_all() -> None:
    registry = CacheRegistry()
    cache_a = TTLCache[int, int](ttl_seconds=10, name="cache.a")
    cache_b = TTLCache[int, int](ttl_seconds=10, name="cache.b")
    registry.register(cache_a)
    registry.register(cache_b)

    cache_a.get(1, lambda: 42)
    cache_b.get(2, lambda: 84)
    registry.invalidate()

    assert cache_a.size() == 0
    assert cache_b.size() == 0


def test_global_registry_registers_named_caches() -> None:
    _ = TTLCache[int, int](ttl_seconds=10, name="global.cache")
    registry = get_cache_registry()
    assert "global.cache" in registry.list_caches()
    registry.invalidate("global.cache")
