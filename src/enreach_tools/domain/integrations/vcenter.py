"""Typed models for vCenter inventory data."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class VCenterVM:
    """Normalized representation of a vCenter virtual machine."""

    vm_id: str
    name: str
    power_state: str | None
    cpu_count: int | None
    memory_mib: int | None
    guest_os: str | None
    tools_status: str | None
    hardware_version: str | None
    is_template: bool | None
    instance_uuid: str | None
    bios_uuid: str | None
    ip_addresses: tuple[str, ...]
    mac_addresses: tuple[str, ...]
    host: str | None
    cluster: str | None
    datacenter: str | None
    resource_pool: str | None
    folder: str | None
    guest_family: str | None = None
    guest_name: str | None = None
    guest_full_name: str | None = None
    guest_host_name: str | None = None
    guest_ip_address: str | None = None
    tools_run_state: str | None = None
    tools_version: str | None = None
    tools_version_status: str | None = None
    tools_install_type: str | None = None
    tools_auto_update_supported: bool | None = None
    vcenter_url: str | None = None
    network_names: tuple[str, ...] = field(default_factory=tuple)
    custom_attributes: dict[str, str] = field(default_factory=dict)
    tags: tuple[str, ...] = field(default_factory=tuple)
    raw_summary: Mapping[str, Any] | None = None
    raw_detail: Mapping[str, Any] | None = None
