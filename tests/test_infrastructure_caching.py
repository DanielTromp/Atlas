from enreach_tools.infrastructure.caching import TTLCache


def test_ttlcache_loader_called_once():
    calls = {"count": 0}

    def loader() -> int:
        calls["count"] += 1
        return calls["count"]

    cache = TTLCache[int, int](ttl_seconds=60)
    assert cache.get(1, loader) == 1
    assert cache.get(1, loader) == 1
    cache.invalidate(1)
    assert cache.get(1, loader) == 2
