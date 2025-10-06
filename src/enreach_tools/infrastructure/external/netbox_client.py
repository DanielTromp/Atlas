"""Typed NetBox adapter with caching and async hooks."""
from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
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

    def list_device_metadata(self) -> Mapping[str, str]:
        return self._fetch_metadata(self._nb.dcim.devices)

    def list_vm_metadata(self) -> Mapping[str, str]:
        return self._fetch_metadata(self._nb.virtualization.virtual_machines)

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

    def get_devices_by_ids(self, identifiers: Iterable[int]) -> Sequence[NetboxDeviceRecord]:
        results: list[NetboxDeviceRecord] = []
        for identifier in identifiers:
            try:
                results.append(self.get_device(identifier))
            except Exception:
                continue
        dedup: dict[int, NetboxDeviceRecord] = {int(record.id): record for record in results}
        return tuple(dedup[idx] for idx in sorted(dedup))

    def get_vms_by_ids(self, identifiers: Iterable[int]) -> Sequence[NetboxVMRecord]:
        results: list[NetboxVMRecord] = []
        for identifier in identifiers:
            try:
                results.append(self.get_vm(identifier))
            except Exception:
                continue
        dedup: dict[int, NetboxVMRecord] = {int(record.id): record for record in results}
        return tuple(dedup[idx] for idx in sorted(dedup))

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

    def _fetch_metadata(self, endpoint) -> dict[str, str]:
        metadata: dict[str, str] = {}
        iterator: Iterable[Any] | None = None
        try:
            iterator = endpoint.values("id", "last_updated")
        except Exception:
            iterator = None
        if iterator is None:
            try:
                iterator = endpoint.filter(limit=0, fields="id,last_updated")
            except Exception:
                iterator = None
        if iterator is None:
            return metadata
        for item in iterator:
            if isinstance(item, Mapping):
                identifier = item.get("id")
                last_updated = item.get("last_updated")
            elif isinstance(item, (tuple, list)) and len(item) >= 2:
                identifier, last_updated = item[0], item[1]
            else:
                identifier = getattr(item, "id", None)
                last_updated = getattr(item, "last_updated", None)
            if identifier is None:
                continue
            metadata[str(identifier)] = _normalize_last_updated(last_updated)
        return metadata


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


def _normalize_last_updated(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return ""
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except Exception:
            return str(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    normalized = dt.astimezone(timezone.utc).replace(microsecond=0)
    return normalized.isoformat().replace("+00:00", "Z")


def _choice_label(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        label = value.get("label") or value.get("name") or value.get("value")
        return str(label) if label not in (None, "") else None
    return str(value)


def _traverse(payload: Any, key: str) -> Any:
    if payload is None:
        return None
    if isinstance(payload, Mapping):
        return payload.get(key)
    if hasattr(payload, key):
        try:
            return getattr(payload, key)
        except Exception:  # pragma: no cover - defensive
            return None
    return None


def _stringify_label(value: Any) -> str | None:
    def _clean(text: str | None) -> str | None:
        if text is None:
            return None
        candidate = text.strip()
        if not candidate or candidate.isdigit():
            return None
        return candidate

    if value is None:
        return None
    if isinstance(value, str):
        return _clean(value)
    if isinstance(value, int | float):
        return None

    result: str | None = None
    if isinstance(value, Mapping):
        for candidate in ("display", "name", "label", "value", "slug"):
            result = _stringify_label(value.get(candidate))
            if result:
                break
        return result

    for candidate in ("display", "name", "label", "value", "slug"):
        if hasattr(value, candidate):
            result = _stringify_label(getattr(value, candidate))
            if result:
                break
    if result is None and hasattr(value, "__str__"):
        result = _clean(str(value))
    return result


def _nested_name(payload: Any, *path: str) -> str | None:
    target = payload
    for key in path:
        target = _traverse(target, key)
        if target is None:
            return None
    return _stringify_label(target)


def _resolve_related_name(record_obj: Any, data: Mapping[str, JSONValue], *path: str) -> str | None:
    direct = _nested_name(data, *path)
    if direct:
        return direct
    return _nested_name(record_obj, *path)


def _is_id_like(value: str) -> bool:
    value = value.strip()
    if not value:
        return False
    return value.isdigit()


def _stringify_ip(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        for key in ("address", "ip", "value", "display"):
            href = value.get(key)
            if href:
                text = str(href).strip()
                if text and not _is_id_like(text):
                    return text
        return None
    # pynetbox IpAddresses records expose an ``address`` attribute and a useful ``__str__``
    for attr in ("address", "ip", "value", "display"):
        if hasattr(value, attr):
            candidate = getattr(value, attr)
            if candidate:
                text = str(candidate).strip()
                if text and not _is_id_like(text):
                    return text
    text = str(value).strip()
    if not text or text.lower() in {"none", "null"} or _is_id_like(text):
        return None
    return text


def _resolve_ip(record_obj: Any, data: Mapping[str, JSONValue], attr: str) -> str | None:
    direct = _stringify_ip(data.get(attr)) if isinstance(data, Mapping) else None
    if direct:
        return direct
    if record_obj is None:
        return None
    fallback = getattr(record_obj, attr, None)
    if fallback is None:
        return None
    return _stringify_ip(fallback)


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
    manufacturer = (
        _resolve_related_name(record, data, "device_type", "manufacturer")
        or _nested_name(device_type)
    )
    rack_face = _resolve_related_name(record, data, "face")
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
        role=_resolve_related_name(record, data, "role"),
        tenant=_resolve_related_name(record, data, "tenant"),
        tenant_group=_resolve_related_name(record, data, "tenant", "group"),
        site=_resolve_related_name(record, data, "site"),
        location=_resolve_related_name(record, data, "location"),
        tags=_tags(data.get("tags")),
        last_updated=_dt(data.get("last_updated")),
        primary_ip=_resolve_ip(record, data, "primary_ip"),
        primary_ip4=_resolve_ip(record, data, "primary_ip4"),
        primary_ip6=_resolve_ip(record, data, "primary_ip6"),
        oob_ip=_resolve_ip(record, data, "oob_ip"),
        custom_fields=_custom_fields(data.get("custom_fields")),
        raw=data,
        source=record,
        manufacturer=manufacturer,
        model=
            _resolve_related_name(record, data, "device_type", "model")
            or _nested_name(device_type, "model")
            or _resolve_related_name(record, data, "model"),
        rack=_resolve_related_name(record, data, "rack"),
        rack_unit=rack_unit,
        serial=str(data.get("serial")) if data.get("serial") not in (None, "") else None,
        asset_tag=str(data.get("asset_tag")) if data.get("asset_tag") not in (None, "") else None,
        cluster=_resolve_related_name(record, data, "cluster"),
        site_group=_resolve_related_name(record, data, "site", "group"),
        region=_resolve_related_name(record, data, "site", "region"),
        description=str(data.get("description")) if data.get("description") else None,
    )


def _build_vm_record(record: Any) -> NetboxVMRecord:
    data = _serialize(record)
    return NetboxVMRecord(
        id=int(data.get("id") or getattr(record, "id", 0)),
        name=str(data.get("name") or getattr(record, "name", "")),
        status=_nested_name(data.get("status"), "value"),
        status_label=_choice_label(data.get("status")),
        role=_resolve_related_name(record, data, "role"),
        tenant=_resolve_related_name(record, data, "tenant"),
        tenant_group=_resolve_related_name(record, data, "tenant", "group"),
        site=_resolve_related_name(record, data, "site"),
        location=
            _resolve_related_name(record, data, "cluster", "site")
            or _resolve_related_name(record, data, "site", "name"),
        tags=_tags(data.get("tags")),
        last_updated=_dt(data.get("last_updated")),
        primary_ip=_resolve_ip(record, data, "primary_ip"),
        primary_ip4=_resolve_ip(record, data, "primary_ip4"),
        primary_ip6=_resolve_ip(record, data, "primary_ip6"),
        oob_ip=_resolve_ip(record, data, "oob_ip"),
        custom_fields=_custom_fields(data.get("custom_fields")),
        raw=data,
        source=record,
        cluster=_resolve_related_name(record, data, "cluster"),
        role_detail=_choice_label(data.get("role")),
        platform=_resolve_related_name(record, data, "platform"),
        description=str(data.get("description")) if data.get("description") else None,
    )


__all__ = ["NetboxClient", "NetboxClientConfig"]
