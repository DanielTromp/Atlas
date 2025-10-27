"""Typed models describing NetBox records consumed by the application."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TypeAlias

JSONPrimitive: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONPrimitive | Sequence["JSONValue"] | Mapping[str, "JSONValue"]


@dataclass(slots=True)
class NetboxBaseRecord:
    """Shared metadata for any NetBox object we export or render."""

    id: int
    name: str
    status: str | None
    status_label: str | None
    role: str | None
    tenant: str | None
    tenant_group: str | None
    site: str | None
    location: str | None
    tags: tuple[str, ...]
    last_updated: datetime | None
    primary_ip: str | None
    primary_ip4: str | None
    primary_ip6: str | None
    oob_ip: str | None
    custom_fields: Mapping[str, JSONValue]
    raw: Mapping[str, JSONValue]
    source: object | None = None

    @property
    def primary_ip_best(self) -> str | None:
        return self.primary_ip or self.primary_ip4 or self.primary_ip6 or self.oob_ip


@dataclass(slots=True)
class NetboxDeviceRecord(NetboxBaseRecord):
    """Device-centric NetBox export payload."""

    manufacturer: str | None = None
    model: str | None = None
    rack: str | None = None
    rack_unit: str | None = None
    serial: str | None = None
    asset_tag: str | None = None
    cluster: str | None = None
    site_group: str | None = None
    region: str | None = None
    description: str | None = None


@dataclass(slots=True)
class NetboxVMRecord(NetboxBaseRecord):
    """Virtual machine representation for NetBox exports."""

    cluster: str | None = None
    role_detail: str | None = None
    platform: str | None = None
    description: str | None = None
