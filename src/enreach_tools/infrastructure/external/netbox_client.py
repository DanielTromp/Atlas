"""Typed NetBox adapter with caching and async hooks."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

try:  # optional dependency
    import pynetbox
except Exception:  # pragma: no cover - adapter functions guard against missing dep
    pynetbox = None  # type: ignore

from enreach_tools.infrastructure.caching import TTLCache


@dataclass(slots=True)
class NetboxClientConfig:
    url: str
    token: str
    cache_ttl_seconds: float = 300.0


class NetboxClient:
    """Provide typed access to NetBox resources with in-memory caching.

    The implementation keeps a thin surface so that future refactors can swap in
    API clients, pagination, or async streaming without touching call sites.
    """

    def __init__(self, config: NetboxClientConfig) -> None:
        if not config.url or not config.token:
            raise ValueError("NetBox URL and token are required")
        if pynetbox is None:
            raise RuntimeError("pynetbox is not installed; install it to use NetboxClient")
        self._config = config
        self._nb = pynetbox.api(config.url, token=config.token)
        self._device_cache = TTLCache[str, Sequence[dict[str, Any]]](config.cache_ttl_seconds)
        self._vm_cache = TTLCache[str, Sequence[dict[str, Any]]](config.cache_ttl_seconds)

    def list_devices(self, *, force_refresh: bool = False) -> Sequence[dict[str, Any]]:
        if force_refresh:
            self._device_cache.invalidate()
        return self._device_cache.get("devices", self._fetch_devices)

    def list_vms(self, *, force_refresh: bool = False) -> Sequence[dict[str, Any]]:
        if force_refresh:
            self._vm_cache.invalidate()
        return self._vm_cache.get("vms", self._fetch_vms)

    async def list_devices_async(self, *, force_refresh: bool = False) -> Sequence[dict[str, Any]]:
        return await asyncio.to_thread(self.list_devices, force_refresh=force_refresh)

    async def list_vms_async(self, *, force_refresh: bool = False) -> Sequence[dict[str, Any]]:
        return await asyncio.to_thread(self.list_vms, force_refresh=force_refresh)

    def _fetch_devices(self) -> Sequence[dict[str, Any]]:
        records: Iterable[Any] = self._nb.dcim.devices.all()  # type: ignore[attr-defined]
        return [self._serialize(record) for record in records]

    def _fetch_vms(self) -> Sequence[dict[str, Any]]:
        records: Iterable[Any] = self._nb.virtualization.virtual_machines.all()  # type: ignore[attr-defined]
        return [self._serialize(record) for record in records]

    @staticmethod
    def _serialize(record: Any) -> dict[str, Any]:
        if hasattr(record, "_values"):
            return dict(record._values)
        if hasattr(record, "dict"):
            return record.dict()  # type: ignore[attr-defined]
        if hasattr(record, "__dict__"):
            return dict(record.__dict__)
        raise TypeError(f"Unsupported NetBox record type: {type(record)!r}")


__all__ = ["NetboxClient", "NetboxClientConfig"]
