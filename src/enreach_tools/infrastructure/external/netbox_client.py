"""Typed NetBox adapter with caching and async hooks."""
from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

try:  # optional dependency
    import pynetbox
except Exception:  # pragma: no cover - adapter functions guard against missing dep
    pynetbox = None  # type: ignore

from enreach_tools.domain.integrations import NetboxDeviceRecord, NetboxVMRecord
from enreach_tools.domain.integrations.netbox import JSONValue
from enreach_tools.infrastructure.caching import CacheMetrics, TTLCache


@dataclass(slots=True)
class NetboxClientConfig:
    url: str
    token: str
    cache_ttl_seconds: float = 300.0


class NetboxClient:
    """Provide typed access to NetBox resources with in-memory caching."""

    def __init__(self, config: NetboxClientConfig) -> None:
        if not config.url or not config.token:
            raise ValueError("NetBox URL and token are required")
        if pynetbox is None:
            raise RuntimeError("pynetbox is not installed; install it to use NetboxClient")
        self._config = config
        self._nb = pynetbox.api(config.url, token=config.token)
        self._device_cache = TTLCache[str, Sequence[NetboxDeviceRecord]](
            ttl_seconds=config.cache_ttl_seconds,
            name="netbox.devices",
        )
        self._vm_cache = TTLCache[str, Sequence[NetboxVMRecord]](
            ttl_seconds=config.cache_ttl_seconds,
            name="netbox.vms",
        )

    def list_devices(self, *, force_refresh: bool = False) -> Sequence[NetboxDeviceRecord]:
        if force_refresh:
            self._device_cache.invalidate()
        return self._device_cache.get("devices", self._fetch_devices)

    def list_vms(self, *, force_refresh: bool = False) -> Sequence[NetboxVMRecord]:
        if force_refresh:
            self._vm_cache.invalidate()
        return self._vm_cache.get("vms", self._fetch_vms)

    async def list_devices_async(self, *, force_refresh: bool = False) -> Sequence[NetboxDeviceRecord]:
        return await asyncio.to_thread(self.list_devices, force_refresh=force_refresh)

    async def list_vms_async(self, *, force_refresh: bool = False) -> Sequence[NetboxVMRecord]:
        return await asyncio.to_thread(self.list_vms, force_refresh=force_refresh)

    def get_device(self, device_id: str | int) -> NetboxDeviceRecord:
        raw = self._nb.dcim.devices.get(device_id)
        if raw is None:
            raise LookupError(f"Device {device_id} not found")
        return _build_device_record(raw)

    def get_vm(self, vm_id: str | int) -> NetboxVMRecord:
        raw = self._nb.virtualization.virtual_machines.get(vm_id)
        if raw is None:
            raise LookupError(f"Virtual machine {vm_id} not found")
        return _build_vm_record(raw)

    @property
    def api(self):  # pragma: no cover - convenience for legacy paths
        return self._nb

    def invalidate_cache(self) -> None:
        self._device_cache.invalidate()
        self._vm_cache.invalidate()

    def cache_metrics(self) -> Mapping[str, CacheMetrics]:
        return {
            "devices": self._device_cache.snapshot_metrics(),
            "vms": self._vm_cache.snapshot_metrics(),
        }

    def _fetch_devices(self) -> Sequence[NetboxDeviceRecord]:
        records: Iterable[Any] = self._nb.dcim.devices.all()  # type: ignore[attr-defined]
        return tuple(_build_device_record(it) for it in records)

    def _fetch_vms(self) -> Sequence[NetboxVMRecord]:
        records: Iterable[Any] = self._nb.virtualization.virtual_machines.all()  # type: ignore[attr-defined]
        return tuple(_build_vm_record(it) for it in records)


def _serialize(record: Any) -> Mapping[str, JSONValue]:
    data: Mapping[str, JSONValue]
    if hasattr(record, "serialize"):
        data = record.serialize()  # type: ignore[assignment]
    elif hasattr(record, "dict"):
        data = record.dict()  # type: ignore[assignment]
    elif hasattr(record, "_asdict"):
        data = record._asdict()  # type: ignore[assignment]
    elif isinstance(record, Mapping):
        data = record  # type: ignore[assignment]
    else:
        try:
            data = dict(record)  # type: ignore[assignment]
        except Exception:  # pragma: no cover - best effort fallback
            data = {}
    return data


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _choice_label(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        label = value.get("label") or value.get("name") or value.get("value")
        return str(label) if label not in (None, "") else None
    return str(value)


def _nested_name(payload: Mapping[str, JSONValue] | None, *path: str) -> str | None:
    data: Any = payload
    for key in path:
        if not isinstance(data, Mapping):
            return None
        data = data.get(key)
    if data is None:
        return None
    if isinstance(data, Mapping):
        for candidate in ("name", "display", "label", "value"):
            if data.get(candidate):
                return str(data[candidate])
        return None
    return str(data)


def _stringify_ip(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        href = value.get("address") or value.get("ip") or value.get("value")
        if href:
            return str(href)
    return str(value)


def _tags(payload: Any) -> tuple[str, ...]:
    out: list[str] = []
    if isinstance(payload, Sequence):
        for item in payload:
            if isinstance(item, Mapping):
                name = item.get("name") or item.get("label") or item.get("slug")
                if name:
                    out.append(str(name))
            elif item:
                out.append(str(item))
    return tuple(sorted({t for t in out if t}))


def _custom_fields(payload: Any) -> Mapping[str, JSONValue]:
    if isinstance(payload, Mapping):
        return payload
    return {}


def _build_device_record(record: Any) -> NetboxDeviceRecord:
    data = _serialize(record)
    device_type = data.get("device_type") if isinstance(data, Mapping) else None
    manufacturer = _nested_name(device_type if isinstance(device_type, Mapping) else None, "manufacturer")
    rack_face = _nested_name(data.get("face") if isinstance(data.get("face"), Mapping) else None)
    position = data.get("position")
    rack_unit = None
    if position not in (None, ""):
        pieces = [p for p in (rack_face, str(position) if position is not None else None) if p]
        rack_unit = " ".join(pieces) if pieces else None
    return NetboxDeviceRecord(
        id=int(data.get("id") or getattr(record, "id", 0)),
        name=str(data.get("name") or getattr(record, "name", "")),
        status=_nested_name(data.get("status"), "value"),
        status_label=_choice_label(data.get("status")),
        role=_nested_name(data.get("role")),
        tenant=_nested_name(data.get("tenant")),
        tenant_group=_nested_name(data.get("tenant"), "group"),
        site=_nested_name(data.get("site")),
        location=_nested_name(data.get("location")),
        tags=_tags(data.get("tags")),
        last_updated=_dt(data.get("last_updated")),
        primary_ip=_stringify_ip(data.get("primary_ip")),
        primary_ip4=_stringify_ip(data.get("primary_ip4")),
        primary_ip6=_stringify_ip(data.get("primary_ip6")),
        oob_ip=_stringify_ip(data.get("oob_ip")),
        custom_fields=_custom_fields(data.get("custom_fields")),
        raw=data,
        source=record,
        manufacturer=manufacturer,
        model=_nested_name(device_type if isinstance(device_type, Mapping) else None, "model") or _nested_name(data, "model"),
        rack=_nested_name(data.get("rack")),
        rack_unit=rack_unit,
        serial=str(data.get("serial")) if data.get("serial") not in (None, "") else None,
        asset_tag=str(data.get("asset_tag")) if data.get("asset_tag") not in (None, "") else None,
        cluster=_nested_name(data.get("cluster")),
        site_group=_nested_name(data.get("site"), "group"),
        region=_nested_name(data.get("site"), "region"),
        description=str(data.get("description")) if data.get("description") else None,
    )


def _build_vm_record(record: Any) -> NetboxVMRecord:
    data = _serialize(record)
    return NetboxVMRecord(
        id=int(data.get("id") or getattr(record, "id", 0)),
        name=str(data.get("name") or getattr(record, "name", "")),
        status=_nested_name(data.get("status"), "value"),
        status_label=_choice_label(data.get("status")),
        role=_nested_name(data.get("role")),
        tenant=_nested_name(data.get("tenant")),
        tenant_group=_nested_name(data.get("tenant"), "group"),
        site=_nested_name(data.get("site")),
        location=_nested_name(data.get("cluster"), "site"),
        tags=_tags(data.get("tags")),
        last_updated=_dt(data.get("last_updated")),
        primary_ip=_stringify_ip(data.get("primary_ip")),
        primary_ip4=_stringify_ip(data.get("primary_ip4")),
        primary_ip6=_stringify_ip(data.get("primary_ip6")),
        oob_ip=_stringify_ip(data.get("oob_ip")),
        custom_fields=_custom_fields(data.get("custom_fields")),
        raw=data,
        source=record,
        cluster=_nested_name(data.get("cluster")),
        role_detail=_choice_label(data.get("role")),
        platform=_nested_name(data.get("platform")),
        description=str(data.get("description")) if data.get("description") else None,
    )


__all__ = ["NetboxClient", "NetboxClientConfig"]
