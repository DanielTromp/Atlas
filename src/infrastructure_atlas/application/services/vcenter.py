"""Services for managing vCenter configurations, caching, and inventory."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from infrastructure_atlas.domain.entities import VCenterConfigEntity
from infrastructure_atlas.domain.integrations.vcenter import VCenterVM
from infrastructure_atlas.domain.repositories import VCenterConfigRepository
from infrastructure_atlas.env import project_root
from infrastructure_atlas.infrastructure.external import (
    ESXiClient,
    VCenterAuthError,
    VCenterClient,
    VCenterClientConfig,
    VCenterClientError,
)
from infrastructure_atlas.infrastructure.logging import get_logger
from infrastructure_atlas.infrastructure.security.secret_store import require_secret_store

logger = get_logger(__name__)

CACHE_DIR_ENV = "VCENTER_CACHE_DIR"
_CACHE_LOCK = Lock()
_CACHE_LOCKS: dict[str, Lock] = {}


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _isoformat(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    value = dt.astimezone(UTC).isoformat()
    return value.replace("+00:00", "Z")


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        normalized = text.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).astimezone(UTC)
    except ValueError:
        return None


def _resolve_cache_dir() -> Path:
    raw = (os.getenv(CACHE_DIR_ENV) or "").strip()
    if raw:
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = project_root() / candidate
    else:
        candidate = project_root() / "data" / "vcenter"
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


def _cache_lock_for(config_id: str) -> Lock:
    with _CACHE_LOCK:
        return _CACHE_LOCKS.setdefault(config_id, Lock())


def _safe_int(value: Any) -> int | None:
    result: int | None = None
    try:
        if isinstance(value, bool):
            result = int(value)
        elif isinstance(value, int):
            result = value
        elif isinstance(value, float):
            result = round(value)
        elif isinstance(value, str):
            cleaned = value.strip()
            if cleaned:
                result = int(float(cleaned))
    except Exception:
        result = None
    return result


def _normalise_name(value: str) -> str:
    text = (value or "").strip()
    if not text:
        raise ValueError("Name is required")
    if len(text) > 80:
        raise ValueError("Name must be 80 characters or fewer")
    return text


def _normalise_username(value: str) -> str:
    text = (value or "").strip()
    if not text:
        raise ValueError("Username is required")
    return text


def _normalise_base_url(value: str) -> str:
    text = (value or "").strip()
    if not text:
        raise ValueError("Base URL is required")
    if not text.lower().startswith(("http://", "https://")):
        text = f"https://{text}"
    parsed = urlparse(text)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("Base URL must include a valid scheme and host (e.g. https://vcenter.example.com)")
    path = parsed.path.rstrip("/") if parsed.path else ""
    rebuilt = f"{parsed.scheme}://{parsed.netloc}{path}"
    return rebuilt.rstrip("/")


def _clean_password(value: str | None) -> str:
    text = (value or "").strip()
    if not text:
        raise ValueError("Password is required")
    return text


def _looks_like_ref(value: str) -> bool:
    text = value.strip()
    if not text or " " in text:
        return False
    lowered = text.lower()
    prefixes = (
        "domain-",
        "datacenter-",
        "cluster-",
        "host-",
        "resgroup-",
        "resourcepool-",
        "resource-pool-",
        "group-",
        "folder-",
    )
    return any(lowered.startswith(prefix) for prefix in prefixes)


def _collect_reference_ids(value: Any, fallback_keys: tuple[str, ...] = ()) -> set[str]:
    identifiers: set[str] = set()
    if isinstance(value, str):
        if _looks_like_ref(value):
            identifiers.add(value.strip())
        return identifiers
    if not isinstance(value, Mapping):
        return identifiers
    for key in ("id", "value", *fallback_keys):
        raw = value.get(key)
        if isinstance(raw, str) and _looks_like_ref(raw):
            identifiers.add(raw.strip())
    for raw in value.values():
        if isinstance(raw, str) and _looks_like_ref(raw):
            identifiers.add(raw.strip())
    return identifiers


def _extract_placement_raw(detail: Mapping[str, Any] | None, key: str) -> Any:
    if not isinstance(detail, Mapping):
        return None
    direct_value = detail.get(key)
    if direct_value is not None:
        return direct_value
    placement = detail.get("placement")
    if not isinstance(placement, Mapping):
        return None
    return placement.get(key)


def _normalise_reference(
    value: Any,
    lookup: Mapping[str, str],
    fallback_keys: tuple[str, ...] = (),
) -> str | None:
    candidate_label: str | None = None
    candidate_id: str | None = None

    if isinstance(value, str):
        candidate_id = value.strip() or None
    elif isinstance(value, Mapping):
        for key in ("name", "display_name", "label", "value"):
            raw = value.get(key)
            if isinstance(raw, str) and raw.strip():
                candidate_label = raw.strip()
                break
        if candidate_label is None:
            for key in (*fallback_keys, "id", "identifier", "value"):
                raw = value.get(key)
                if isinstance(raw, str) and raw.strip():
                    candidate_id = raw.strip()
                    break
        if candidate_id is None:
            for raw in value.values():
                if isinstance(raw, str) and raw.strip():
                    candidate_id = raw.strip()
                    break

    if candidate_label:
        return candidate_label
    if candidate_id:
        mapped = lookup.get(candidate_id) or lookup.get(candidate_id.lower())
        return mapped or candidate_id
    return None


def _resolve_reference(
    primary: Any,
    secondary: Any,
    lookup: Mapping[str, str],
    fallback_keys: tuple[str, ...] = (),
) -> str | None:
    for candidate in (primary, secondary):
        label = _normalise_reference(candidate, lookup, fallback_keys)
        if label:
            return label
    return None


def _collect_guest_ips(interfaces: Iterable[Mapping[str, Any]]) -> set[str]:
    ips: set[str] = set()
    for iface in interfaces:
        if not isinstance(iface, Mapping):
            continue
        ip_info = iface.get("ip")
        if not isinstance(ip_info, Mapping):
            continue
        ip_addresses = ip_info.get("ip_addresses")
        if isinstance(ip_addresses, Iterable):
            for entry in ip_addresses:
                if not isinstance(entry, Mapping):
                    continue
                raw = entry.get("ip_address") or entry.get("value") or entry.get("address")
                if isinstance(raw, str) and raw.strip():
                    ips.add(raw.strip())
        for family in ("ipv4", "ipv6"):
            family_info = ip_info.get(family)
            if not isinstance(family_info, Mapping):
                continue
            addresses = family_info.get("addresses")
            if isinstance(addresses, Iterable):
                for addr in addresses:
                    if isinstance(addr, str) and addr.strip():
                        ips.add(addr.strip())
                    elif isinstance(addr, Mapping):
                        raw = addr.get("ip_address") or addr.get("value")
                        if isinstance(raw, str) and raw.strip():
                            ips.add(raw.strip())
    return ips


def _collect_guest_macs(interfaces: Iterable[Mapping[str, Any]]) -> set[str]:
    macs: set[str] = set()
    for iface in interfaces:
        if not isinstance(iface, Mapping):
            continue
        mac = iface.get("mac_address") or iface.get("mac")
        if isinstance(mac, str):
            cleaned = mac.strip().lower()
            if cleaned:
                macs.add(cleaned)
    return macs


def _collect_detail_ips(detail: Mapping[str, Any] | None) -> set[str]:
    if not isinstance(detail, Mapping):
        return set()
    ips: set[str] = set()
    nics = detail.get("nics")
    if isinstance(nics, Iterable):
        for nic in nics:
            candidate = nic
            if isinstance(nic, Mapping) and "value" in nic:
                candidate = nic.get("value")
            if not isinstance(candidate, Mapping):
                continue
            ip_field = candidate.get("ip_addresses") or candidate.get("ip")
            if isinstance(ip_field, Mapping):
                addresses = ip_field.get("addresses")
                if isinstance(addresses, Iterable):
                    for addr in addresses:
                        if isinstance(addr, str):
                            cleaned = addr.strip()
                            if cleaned:
                                ips.add(cleaned)
            elif isinstance(ip_field, Iterable) and not isinstance(ip_field, str | bytes):
                for addr in ip_field:
                    if isinstance(addr, str):
                        cleaned = addr.strip()
                        if cleaned:
                            ips.add(cleaned)
    return ips


def _collect_detail_macs(detail: Mapping[str, Any] | None) -> set[str]:
    if not isinstance(detail, Mapping):
        return set()
    macs: set[str] = set()
    nics = detail.get("nics")
    if isinstance(nics, Iterable):
        for nic in nics:
            candidate = nic
            if isinstance(nic, Mapping) and "value" in nic:
                candidate = nic.get("value")
            if not isinstance(candidate, Mapping):
                continue
            mac = candidate.get("mac_address")
            if isinstance(mac, str):
                cleaned = mac.strip().lower()
                if cleaned:
                    macs.add(cleaned)
    return macs


def _normalize_text(value: Any) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned:
            return cleaned
    return None


def _build_vm_link(
    base_url: str | None,
    vm_id: str | None,
    *,
    server_guid: str | None = None,
    instance_uuid: str | None = None,
    is_esxi: bool = False,
) -> str | None:
    if not base_url or not vm_id:
        return None
    vm_ref = _normalize_text(str(vm_id))
    if not vm_ref:
        return None
    root = base_url.rstrip("/")
    if is_esxi:
        return f"{root}/ui/#/host/vms/{vm_ref}"
    guid_ref = _normalize_text(server_guid) or _normalize_text(instance_uuid) or vm_ref
    return f"{root}/ui/app/vm;nav=h/urn:vmomi:VirtualMachine:{vm_ref}:{guid_ref}/summary"


def _derive_tools_status(
    existing: str | None,
    tools_info: Mapping[str, Any] | None,
) -> str | None:
    if isinstance(existing, str):
        cleaned = existing.strip()
        if cleaned:
            return cleaned
    if not isinstance(tools_info, Mapping):
        return None
    version_status = _normalize_text(tools_info.get("version_status"))
    run_state = _normalize_text(tools_info.get("run_state"))
    if version_status:
        status_map = {
            "NOT_INSTALLED": "toolsNotInstalled",
            "NOT_RUNNING": "toolsNotRunning",
            "OUT_OF_DATE": "toolsOld",
            "BLACKLISTED": "toolsBlacklisted",
            "TOO_NEW": "toolsTooNew",
            "TOO_OLD": "toolsTooOld",
            "UNMANAGED": "toolsOk",
            "MANAGED": "toolsOk",
        }
        mapped = status_map.get(version_status.upper())
        if mapped:
            return mapped
    if run_state:
        run_map = {
            "RUNNING": "toolsOk",
            "STOPPED": "toolsNotRunning",
            "STOPPING": "toolsNotRunning",
            "PAUSED": "toolsNotRunning",
            "FAILED": "toolsNotRunning",
        }
        mapped = run_map.get(run_state.upper())
        if mapped:
            return mapped
        return run_state
    return version_status


def _build_vm(  # noqa: PLR0913
    summary: Mapping[str, Any],
    detail: Mapping[str, Any] | None,
    guest_interfaces: Iterable[Mapping[str, Any]],
    lookups: Mapping[str, Mapping[str, str]],
    custom_attributes: Mapping[str, Any] | None,
    tags: Iterable[str] | None,
    guest_identity: Mapping[str, Any] | None,
    tools_info: Mapping[str, Any] | None,
    snapshots: Iterable[Mapping[str, Any]] | None,
    disks: Iterable[Mapping[str, Any]] | None,
    *,
    base_url: str | None = None,
    server_guid: str | None = None,
    is_esxi: bool = False,
) -> VCenterVM:
    vm_identifier = summary.get("vm") if isinstance(summary, Mapping) else None
    vm_id = str(vm_identifier or detail.get("vm") if isinstance(detail, Mapping) else "").strip()

    name = summary.get("name") if isinstance(summary, Mapping) else None
    if not isinstance(name, str) and isinstance(detail, Mapping):
        name = detail.get("name")
    name_str = (name or "").strip() or vm_id or "(unnamed)"

    power_state = summary.get("power_state") if isinstance(summary, Mapping) else None
    if not isinstance(power_state, str) and isinstance(detail, Mapping):
        power_state = detail.get("power_state")
    if isinstance(power_state, str):
        power_state = power_state.strip().upper() or None

    cpu_count = _safe_int(summary.get("cpu_count")) if isinstance(summary, Mapping) else None
    if cpu_count is None and isinstance(detail, Mapping):
        cpu = detail.get("cpu")
        if isinstance(cpu, Mapping):
            cpu_count = _safe_int(cpu.get("count"))

    memory_mib = _safe_int(summary.get("memory_size_MiB")) if isinstance(summary, Mapping) else None
    if memory_mib is None and isinstance(detail, Mapping):
        memory = detail.get("memory")
        if isinstance(memory, Mapping):
            memory_mib = _safe_int(memory.get("size_MiB"))

    guest_os = None
    if isinstance(summary, Mapping):
        gos = summary.get("guest_OS") or summary.get("guest_os")
        if isinstance(gos, str) and gos.strip():
            guest_os = gos.strip()
    if guest_os is None and isinstance(detail, Mapping):
        gos = detail.get("guest_OS")
        if isinstance(gos, str) and gos.strip():
            guest_os = gos.strip()

    tools_status = None
    if isinstance(detail, Mapping):
        tools = detail.get("tools")
        if isinstance(tools, Mapping):
            status = tools.get("status")
            if isinstance(status, str) and status.strip():
                tools_status = status.strip()

    hardware_version = None
    if isinstance(detail, Mapping):
        hardware = detail.get("hardware")
        if isinstance(hardware, Mapping):
            version = hardware.get("version")
            if isinstance(version, str) and version.strip():
                hardware_version = version.strip()

    is_template = None
    if isinstance(summary, Mapping):
        template_field = summary.get("template") or summary.get("is_template")
        if isinstance(template_field, bool):
            is_template = template_field
        elif isinstance(template_field, str) and template_field.strip():
            is_template = template_field.strip().lower() in {"1", "true", "yes", "on"}
    if is_template is None and isinstance(detail, Mapping):
        identity = detail.get("identity")
        if isinstance(identity, Mapping):
            template_value = identity.get("template")
            if isinstance(template_value, bool):
                is_template = template_value
            elif isinstance(template_value, str) and template_value.strip():
                is_template = template_value.strip().lower() in {"1", "true", "yes", "on"}

    identity = detail.get("identity") if isinstance(detail, Mapping) else None
    instance_uuid = None
    bios_uuid = None
    if isinstance(identity, Mapping):
        inst = identity.get("instance_uuid")
        if isinstance(inst, str) and inst.strip():
            instance_uuid = inst.strip()
        bios = identity.get("bios_uuid")
        if isinstance(bios, str) and bios.strip():
            bios_uuid = bios.strip()

    guest_ifs = list(guest_interfaces or [])
    ip_set = _collect_detail_ips(detail) | _collect_guest_ips(guest_ifs)
    mac_set = _collect_detail_macs(detail) | _collect_guest_macs(guest_ifs)

    host_value = _resolve_reference(
        summary.get("host") if isinstance(summary, Mapping) else None,
        _extract_placement_raw(detail, "host"),
        lookups.get("hosts", {}),
        ("host",),
    )
    cluster_value = _resolve_reference(
        summary.get("cluster") if isinstance(summary, Mapping) else None,
        _extract_placement_raw(detail, "cluster"),
        lookups.get("clusters", {}),
        ("cluster",),
    )
    datacenter_value = _resolve_reference(
        summary.get("datacenter") if isinstance(summary, Mapping) else None,
        _extract_placement_raw(detail, "datacenter"),
        lookups.get("datacenters", {}),
        ("datacenter",),
    )
    resource_pool_value = _resolve_reference(
        summary.get("resource_pool") if isinstance(summary, Mapping) else None,
        _extract_placement_raw(detail, "resource_pool"),
        lookups.get("resource_pools", {}),
        ("resource_pool", "pool"),
    )
    folder_value = _resolve_reference(
        summary.get("folder") if isinstance(summary, Mapping) else None,
        _extract_placement_raw(detail, "folder"),
        lookups.get("folders", {}),
        ("folder",),
    )

    network_names: set[str] = set()
    if isinstance(detail, Mapping):
        nics_detail = detail.get("nics")
        if isinstance(nics_detail, Iterable):
            for nic in nics_detail:
                candidate = nic
                if isinstance(nic, Mapping) and "value" in nic:
                    candidate = nic.get("value")
                if not isinstance(candidate, Mapping):
                    continue
                label = _normalize_text(candidate.get("label"))
                if label:
                    network_names.add(label)
                backing = candidate.get("backing")
                if isinstance(backing, Mapping):
                    network_label = _normalize_text(backing.get("network_name")) or _normalize_text(backing.get("network"))
                    if network_label:
                        network_names.add(network_label)

    guest_family = None
    guest_name_value = None
    guest_full_name = None
    guest_host_name = None
    guest_ip_address = None
    if isinstance(guest_identity, Mapping):
        guest_family = _normalize_text(guest_identity.get("family"))
        guest_name_value = _normalize_text(guest_identity.get("name"))
        host_value_raw = guest_identity.get("host_name")
        guest_host_name = _normalize_text(host_value_raw)
        full_raw = guest_identity.get("full_name")
        if isinstance(full_raw, Mapping):
            guest_full_name = (
                _normalize_text(full_raw.get("default_message"))
                or _normalize_text(full_raw.get("name"))
                or _normalize_text(full_raw.get("id"))
            )
        else:
            guest_full_name = _normalize_text(full_raw)
        guest_ip_address = _normalize_text(guest_identity.get("ip_address"))
        if guest_ip_address:
            ip_set.add(guest_ip_address)

    tools_status = _derive_tools_status(tools_status, tools_info)

    tools_run_state = None
    tools_version = None
    tools_version_status = None
    tools_install_type = None
    tools_auto_update_supported: bool | None = None
    if isinstance(tools_info, Mapping):
        tools_run_state = _normalize_text(tools_info.get("run_state"))
        version_value = tools_info.get("version") or tools_info.get("version_number")
        if version_value is not None:
            tools_version = str(version_value).strip()
        tools_version_status = _normalize_text(tools_info.get("version_status"))
        tools_install_type = _normalize_text(tools_info.get("install_type"))
        auto_update_value = tools_info.get("auto_update_supported")
        if isinstance(auto_update_value, bool):
            tools_auto_update_supported = auto_update_value

    ip_addresses = tuple(sorted(ip_set))
    mac_addresses = tuple(sorted(mac_set))
    vcenter_url = _build_vm_link(
        base_url,
        vm_identifier,
        server_guid=server_guid,
        instance_uuid=instance_uuid,
        is_esxi=is_esxi,
    )

    attr_map: dict[str, str] = {}
    if isinstance(custom_attributes, Mapping):
        for key, value in custom_attributes.items():
            if not isinstance(key, str):
                continue
            cleaned_key = key.strip()
            if not cleaned_key:
                continue
            attr_map[cleaned_key] = str(value).strip() if value is not None else ""

    tag_tuple = tuple(
        str(tag).strip()
        for tag in (tags or ())
        if isinstance(tag, str) and str(tag).strip()
    )

    snapshot_list = list(snapshots or [])
    snapshot_tuple = tuple(dict(s) for s in snapshot_list if isinstance(s, Mapping))
    snapshot_count = len(snapshot_tuple) if snapshot_tuple else None

    disk_list = list(disks or [])
    disk_tuple = tuple(dict(d) for d in disk_list if isinstance(d, Mapping))
    total_capacity = 0
    total_provisioned = 0
    for disk in disk_tuple:
        capacity = disk.get("capacity_bytes")
        if isinstance(capacity, int):
            total_capacity += capacity
        provisioned = disk.get("provisioned_bytes")
        if isinstance(provisioned, int):
            total_provisioned += provisioned
    total_disk_capacity_bytes = total_capacity if total_capacity > 0 else None
    total_provisioned_bytes = total_provisioned if total_provisioned > 0 else None

    return VCenterVM(
        vm_id=vm_id,
        name=name_str,
        power_state=power_state,
        cpu_count=cpu_count,
        memory_mib=memory_mib,
        guest_os=guest_os,
        tools_status=tools_status,
        hardware_version=hardware_version,
        is_template=is_template,
        instance_uuid=instance_uuid,
        bios_uuid=bios_uuid,
        ip_addresses=ip_addresses,
        mac_addresses=mac_addresses,
        host=host_value,
        cluster=cluster_value,
        datacenter=datacenter_value,
        resource_pool=resource_pool_value,
        folder=folder_value,
        guest_family=guest_family,
        guest_name=guest_name_value,
        guest_full_name=guest_full_name,
        guest_host_name=guest_host_name,
        guest_ip_address=guest_ip_address,
        tools_run_state=tools_run_state,
        tools_version=tools_version,
        tools_version_status=tools_version_status,
        tools_install_type=tools_install_type,
        tools_auto_update_supported=tools_auto_update_supported,
        vcenter_url=vcenter_url,
        network_names=tuple(sorted(network_names)),
        custom_attributes=attr_map,
        tags=tag_tuple,
        snapshots=snapshot_tuple,
        snapshot_count=snapshot_count,
        disks=disk_tuple,
        total_disk_capacity_bytes=total_disk_capacity_bytes,
        total_provisioned_bytes=total_provisioned_bytes,
        raw_summary=summary,
        raw_detail=detail,
    )


def _serialize_vm(vm: VCenterVM) -> dict[str, Any]:
    return {
        "id": vm.vm_id,
        "vm_id": vm.vm_id,
        "name": vm.name,
        "power_state": vm.power_state,
        "cpu_count": vm.cpu_count,
        "memory_mib": vm.memory_mib,
        "guest_os": vm.guest_os,
        "tools_status": vm.tools_status,
        "hardware_version": vm.hardware_version,
        "is_template": vm.is_template,
        "instance_uuid": vm.instance_uuid,
        "bios_uuid": vm.bios_uuid,
        "ip_addresses": list(vm.ip_addresses),
        "mac_addresses": list(vm.mac_addresses),
        "host": vm.host,
        "cluster": vm.cluster,
        "datacenter": vm.datacenter,
        "resource_pool": vm.resource_pool,
        "folder": vm.folder,
        "guest_family": vm.guest_family,
        "guest_name": vm.guest_name,
        "guest_full_name": vm.guest_full_name,
        "guest_host_name": vm.guest_host_name,
        "guest_ip_address": vm.guest_ip_address,
        "tools_run_state": vm.tools_run_state,
        "tools_version": vm.tools_version,
        "tools_version_status": vm.tools_version_status,
        "tools_install_type": vm.tools_install_type,
        "tools_auto_update_supported": vm.tools_auto_update_supported,
        "vcenter_url": vm.vcenter_url,
        "network_names": list(vm.network_names),
        "custom_attributes": vm.custom_attributes,
        "tags": list(vm.tags),
        "snapshots": [dict(s) for s in vm.snapshots],
        "snapshot_count": vm.snapshot_count,
        "disks": [dict(d) for d in vm.disks],
        "total_disk_capacity_bytes": vm.total_disk_capacity_bytes,
        "total_provisioned_bytes": vm.total_provisioned_bytes,
    }


def _deserialize_vm(data: Mapping[str, Any]) -> VCenterVM:
    raw_attrs = data.get("custom_attributes")
    custom_attributes: dict[str, str] = {}
    if isinstance(raw_attrs, Mapping):
        for key, value in raw_attrs.items():
            if isinstance(key, str):
                custom_attributes[key] = str(value).strip() if value is not None else ""
    elif isinstance(raw_attrs, list):
        for item in raw_attrs:
            if not isinstance(item, Mapping):
                continue
            key = item.get("name") or item.get("key")
            value = item.get("value")
            if isinstance(key, str) and key.strip():
                custom_attributes[key.strip()] = str(value).strip() if value is not None else ""

    raw_tags = data.get("tags")
    tag_tuple: tuple[str, ...] = ()
    if isinstance(raw_tags, list | tuple):
        tag_tuple = tuple(str(tag).strip() for tag in raw_tags if isinstance(tag, str) and tag.strip())

    raw_networks = data.get("network_names")
    network_names: tuple[str, ...] = ()
    if isinstance(raw_networks, list | tuple):
        network_names = tuple(str(item).strip() for item in raw_networks if isinstance(item, str) and item.strip())

    raw_tools_version = data.get("tools_version")
    tools_version_value = None
    if isinstance(raw_tools_version, int | float):
        tools_version_value = str(raw_tools_version)
    elif isinstance(raw_tools_version, str):
        stripped = raw_tools_version.strip()
        tools_version_value = stripped or None

    auto_update_raw = data.get("tools_auto_update_supported")
    tools_auto_update_supported = auto_update_raw if isinstance(auto_update_raw, bool) else None

    guest_family = _normalize_text(data.get("guest_family"))
    guest_name_value = _normalize_text(data.get("guest_name"))
    guest_full_name = _normalize_text(data.get("guest_full_name"))
    guest_host_name = _normalize_text(data.get("guest_host_name"))
    guest_ip_address = _normalize_text(data.get("guest_ip_address"))
    tools_run_state = _normalize_text(data.get("tools_run_state"))
    tools_version_status = _normalize_text(data.get("tools_version_status"))
    tools_install_type = _normalize_text(data.get("tools_install_type"))
    vcenter_url = _normalize_text(data.get("vcenter_url"))

    raw_snapshots = data.get("snapshots")
    snapshot_tuple: tuple[Mapping[str, Any], ...] = ()
    if isinstance(raw_snapshots, list):
        snapshot_tuple = tuple(dict(s) for s in raw_snapshots if isinstance(s, Mapping))

    snapshot_count = _safe_int(data.get("snapshot_count"))

    raw_disks = data.get("disks")
    disk_tuple: tuple[Mapping[str, Any], ...] = ()
    if isinstance(raw_disks, list):
        disk_tuple = tuple(dict(d) for d in raw_disks if isinstance(d, Mapping))

    total_disk_capacity_bytes = _safe_int(data.get("total_disk_capacity_bytes"))
    total_provisioned_bytes = _safe_int(data.get("total_provisioned_bytes"))

    raw_vm_id = data.get("vm_id") or data.get("id")

    return VCenterVM(
        vm_id=str(raw_vm_id or ""),
        name=str(data.get("name") or ""),
        power_state=data.get("power_state"),
        cpu_count=_safe_int(data.get("cpu_count")),
        memory_mib=_safe_int(data.get("memory_mib")),
        guest_os=data.get("guest_os"),
        tools_status=data.get("tools_status"),
        hardware_version=data.get("hardware_version"),
        is_template=data.get("is_template") if isinstance(data.get("is_template"), bool) else None,
        instance_uuid=data.get("instance_uuid"),
        bios_uuid=data.get("bios_uuid"),
        ip_addresses=tuple(str(v).strip() for v in data.get("ip_addresses", []) if isinstance(v, str) and v.strip()),
        mac_addresses=tuple(
            str(v).strip().lower() for v in data.get("mac_addresses", []) if isinstance(v, str) and v.strip()
        ),
        host=data.get("host"),
        cluster=data.get("cluster"),
        datacenter=data.get("datacenter"),
        resource_pool=data.get("resource_pool"),
        folder=data.get("folder"),
        guest_family=guest_family,
        guest_name=guest_name_value,
        guest_full_name=guest_full_name,
        guest_host_name=guest_host_name,
        guest_ip_address=guest_ip_address,
        tools_run_state=tools_run_state,
        tools_version=tools_version_value,
        tools_version_status=tools_version_status,
        tools_install_type=tools_install_type,
        tools_auto_update_supported=tools_auto_update_supported,
        vcenter_url=vcenter_url,
        network_names=network_names,
        custom_attributes=custom_attributes,
        tags=tag_tuple,
        snapshots=snapshot_tuple,
        snapshot_count=snapshot_count,
        disks=disk_tuple,
        total_disk_capacity_bytes=total_disk_capacity_bytes,
        total_provisioned_bytes=total_provisioned_bytes,
        raw_summary=None,
        raw_detail=None,
    )


class VCenterService:
    """Application service exposing vCenter configuration operations.

    Supports both MongoDB and SQLite backends based on ATLAS_STORAGE_BACKEND.
    For MongoDB backend, uses MongoDB cache repository instead of JSON files.
    """

    def __init__(
        self,
        repo: VCenterConfigRepository,
        session: Session | None = None,
        backend: str = "mongodb",
        cache_repo: Any = None,
    ) -> None:
        self._repo = repo
        self._session = session
        self._backend = backend
        self._cache_repo = cache_repo
        self._cache_dir = _resolve_cache_dir()

    def _repo_instance(self) -> VCenterConfigRepository:
        return self._repo

    def _commit(self) -> None:
        """Commit transaction for SQLite backend."""
        if self._backend == "sqlite" and self._session is not None:
            self._session.commit()

    def _rollback(self) -> None:
        """Rollback transaction for SQLite backend."""
        if self._backend == "sqlite" and self._session is not None:
            self._session.rollback()

    def _cache_dir_path(self) -> Path:
        cache_dir = self._cache_dir
        if cache_dir is None:
            cache_dir = _resolve_cache_dir()
            object.__setattr__(self, "_cache_dir", cache_dir)
        return cache_dir

    def _get_cache_repo(self):
        """Get the MongoDB cache repository (lazy loading)."""
        if self._cache_repo is not None:
            return self._cache_repo
        if self._backend != "mongodb":
            return None
        from infrastructure_atlas.infrastructure.mongodb import get_mongodb_client
        from infrastructure_atlas.infrastructure.mongodb.cache_repositories import MongoDBVCenterCacheRepository
        client = get_mongodb_client()
        self._cache_repo = MongoDBVCenterCacheRepository(client.atlas_cache)
        return self._cache_repo

    # ------------------------------------------------------------------
    # Configuration management
    # ------------------------------------------------------------------
    def list_configs(self) -> list[VCenterConfigEntity]:
        return self._repo_instance().list_all()

    def list_configs_with_status(self) -> list[tuple[VCenterConfigEntity, dict[str, Any]]]:
        results: list[tuple[VCenterConfigEntity, dict[str, Any]]] = []
        repo = self._repo_instance()
        for config in repo.list_all():
            cache = self._load_cache_entry(config.id)
            meta = cache["meta"] if cache else {}
            results.append((config, meta))
        return results

    def get_config(self, config_id: str) -> VCenterConfigEntity | None:
        identifier = (config_id or "").strip()
        if not identifier:
            return None
        return self._repo_instance().get(identifier)

    def create_config(
        self,
        *,
        name: str,
        base_url: str,
        username: str,
        password: str,
        verify_ssl: bool,
        is_esxi: bool = False,
    ) -> VCenterConfigEntity:
        normalised_name = _normalise_name(name)
        normalised_url = _normalise_base_url(base_url)
        normalised_username = _normalise_username(username)
        cleaned_password = _clean_password(password)
        store = require_secret_store()

        config_id = str(uuid.uuid4())
        secret_name = f"vcenter:{config_id}:password"

        try:
            entity = self._repo_instance().create(
                config_id=config_id,
                name=normalised_name,
                base_url=normalised_url,
                username=normalised_username,
                password_secret=secret_name,
                verify_ssl=bool(verify_ssl),
                is_esxi=bool(is_esxi),
            )
        except Exception as exc:
            self._rollback()
            if "already exists" in str(exc).lower() or "duplicate" in str(exc).lower():
                raise ValueError("A vCenter with that name already exists") from exc
            raise

        try:
            store.set(secret_name, cleaned_password)
            self._commit()
        except Exception:
            logger.exception("Failed to persist encrypted password for vCenter '%s'", normalised_name)
            self._rollback()
            try:
                self._repo_instance().delete(entity.id)
                self._commit()
            except Exception:  # pragma: no cover - defensive cleanup
                self._rollback()
            raise

        return entity

    def update_config(  # noqa: PLR0913
        self,
        config_id: str,
        *,
        name: str | None = None,
        base_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        verify_ssl: bool | None = None,
        is_esxi: bool | None = None,
    ) -> VCenterConfigEntity:
        repo = self._repo_instance()
        config = repo.get(config_id)
        if config is None:
            raise ValueError("vCenter configuration not found")

        update_data: dict[str, Any] = {}
        if name is not None:
            update_data["name"] = _normalise_name(name)
        if base_url is not None:
            update_data["base_url"] = _normalise_base_url(base_url)
        if username is not None:
            update_data["username"] = _normalise_username(username)
        if verify_ssl is not None:
            update_data["verify_ssl"] = bool(verify_ssl)
        if is_esxi is not None:
            update_data["is_esxi"] = bool(is_esxi)

        try:
            entity = repo.update(config_id, **update_data)
        except Exception as exc:
            self._rollback()
            if "already exists" in str(exc).lower() or "duplicate" in str(exc).lower():
                raise ValueError("A vCenter with that name already exists") from exc
            raise

        if entity is None:
            raise ValueError("vCenter configuration not found")

        if password is not None:
            cleaned = _clean_password(password)
            store = require_secret_store()
            store.set(entity.password_secret, cleaned)

        self._commit()
        return entity

    def delete_config(self, config_id: str) -> bool:
        repo = self._repo_instance()
        config = repo.get(config_id)
        if config is None:
            return False
        store = require_secret_store()
        removed = repo.delete(config_id)
        if removed:
            store.delete(config.password_secret)
            self._commit()
            # Delete from MongoDB cache if using mongodb backend
            cache_repo = self._get_cache_repo()
            if cache_repo is not None:
                try:
                    cache_repo.delete_vms_for_config(config_id)
                except Exception:
                    logger.warning("Failed to remove vCenter cache from MongoDB for %s", config_id, exc_info=True)
            # Also remove JSON cache file if it exists (for cleanup during migration)
            cache_path = self._cache_path(config_id)
            if cache_path.exists():
                try:
                    cache_path.unlink()
                except Exception:
                    logger.warning("Failed to remove vCenter JSON cache for %s", config_id, exc_info=True)
            return True
        self._rollback()
        return False

    # ------------------------------------------------------------------
    # Inventory and caching
    # ------------------------------------------------------------------
    def refresh_inventory(
        self,
        config_id: str,
        vm_ids: set[str] | None = None,
    ) -> tuple[VCenterConfigEntity, list[VCenterVM], dict[str, Any]]:
        config = self._repo_instance().get(config_id)
        if config is None:
            raise ValueError("vCenter configuration not found")
        store = require_secret_store()
        password = store.get(config.password_secret)
        if not password:
            raise ValueError("Credentials are not configured for this vCenter")

        lock = _cache_lock_for(config.id)
        with lock:
            filters = {vm_id.strip().lower() for vm_id in vm_ids} if vm_ids else None
            vms, meta = self._fetch_inventory_live(config, password, vm_filters=filters)
            # Use partial update when filtering to specific VMs
            is_partial = filters is not None
            self._write_cache(config, vms, meta, partial_update=is_partial)
        meta_with_source = dict(meta)
        meta_with_source["source"] = "live"
        return config, vms, meta_with_source

    def get_inventory(
        self,
        config_id: str,
        *,
        refresh: bool = False,
    ) -> tuple[VCenterConfigEntity, list[VCenterVM], dict[str, Any]]:
        if refresh:
            return self.refresh_inventory(config_id)

        repo = self._repo_instance()
        config = repo.get(config_id)
        if config is None:
            raise ValueError("vCenter configuration not found")

        cache = self._load_cache_entry(config_id)
        if cache:
            meta = dict(cache["meta"])
            meta["source"] = "cache"
            return config, cache["vms"], meta
        return self.refresh_inventory(config_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _cache_path(self, config_id: str) -> Path:
        return self._cache_dir_path() / f"{config_id}.json"

    def _load_cache_entry(self, config_id: str) -> dict[str, Any] | None:
        # Use MongoDB cache for mongodb backend
        cache_repo = self._get_cache_repo()
        if cache_repo is not None:
            return self._load_cache_entry_mongodb(config_id, cache_repo)
        return self._load_cache_entry_json(config_id)

    def _load_cache_entry_mongodb(self, config_id: str, cache_repo) -> dict[str, Any] | None:
        """Load cache from MongoDB."""
        try:
            vms = cache_repo.list_vms(config_id)
            if not vms:
                return None
            meta = cache_repo.get_cache_metadata(config_id) or {}
            return {
                "meta": {
                    "generated_at": meta.get("generated_at"),
                    "vm_count": meta.get("vm_count", len(vms)),
                },
                "vms": vms,
            }
        except Exception:
            logger.warning("Failed to load vCenter cache from MongoDB for %s", config_id, exc_info=True)
            return None

    def _load_cache_entry_json(self, config_id: str) -> dict[str, Any] | None:
        """Load cache from JSON file (legacy)."""
        path = self._cache_path(config_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Failed to read vCenter cache for %s", config_id, exc_info=True)
            return None

        generated_at = _parse_iso_datetime(payload.get("generated_at"))
        vm_payload = payload.get("vms")
        if not isinstance(vm_payload, list):
            return None
        vms: list[VCenterVM] = []
        for item in vm_payload:
            if isinstance(item, Mapping):
                try:
                    vms.append(_deserialize_vm(item))
                except Exception:
                    logger.debug("Skipping malformed VM cache entry for %s", config_id, exc_info=True)
        raw_count = payload.get("vm_count") or payload.get("vm_total")
        if isinstance(raw_count, int | float):
            vm_count = int(raw_count)
        elif isinstance(raw_count, str) and raw_count.strip().isdigit():
            vm_count = int(raw_count.strip())
        else:
            vm_count = len(vms)
        meta = {
            "generated_at": generated_at,
            "vm_count": vm_count,
        }
        return {"meta": meta, "vms": vms}

    def _write_cache(
        self,
        config: VCenterConfigEntity,
        vms: Iterable[VCenterVM],
        meta: Mapping[str, Any],
        *,
        partial_update: bool = False,
    ) -> None:
        # Use MongoDB cache for mongodb backend
        cache_repo = self._get_cache_repo()
        if cache_repo is not None:
            self._write_cache_mongodb(config, vms, partial_update, cache_repo)
        else:
            self._write_cache_json(config, vms, meta, partial_update)

    def _write_cache_mongodb(
        self,
        config: VCenterConfigEntity,
        vms: Iterable[VCenterVM],
        partial_update: bool,
        cache_repo,
    ) -> None:
        """Write cache to MongoDB."""
        vm_list = list(vms)
        try:
            if partial_update:
                # Upsert only the specified VMs (document-level updates)
                cache_repo.upsert_vms(config.id, vm_list)
                logger.debug("Partial update: upserted %d VMs for config %s", len(vm_list), config.id)
            else:
                # Full refresh: replace all VMs for this config
                result = cache_repo.replace_all_vms(config.id, vm_list)
                logger.debug("Full refresh: deleted %d, inserted %d VMs for config %s",
                           result["deleted"], result["inserted"], config.id)
        except Exception:
            logger.warning("Failed to write vCenter cache to MongoDB for %s", config.id, exc_info=True)

    def _write_cache_json(
        self,
        config: VCenterConfigEntity,
        vms: Iterable[VCenterVM],
        meta: Mapping[str, Any],
        partial_update: bool,
    ) -> None:
        """Write cache to JSON file (legacy)."""
        path = self._cache_path(config.id)
        vm_list = list(vms)

        # For partial updates, merge with existing cache
        existing_generated_at = None
        if partial_update and path.exists():
            try:
                existing_cache = self._load_cache_entry_json(config.id)
                if existing_cache:
                    existing_vms = existing_cache.get("vms", [])
                    existing_meta = existing_cache.get("meta", {})
                    existing_generated_at = existing_meta.get("generated_at")

                    # Create a map of updated VMs by vm_id
                    updated_vm_map = {vm.vm_id: vm for vm in vm_list}

                    # Merge: keep existing VMs, update/add new ones
                    merged_vms = []
                    for existing_vm in existing_vms:
                        vm_id = existing_vm.vm_id
                        if vm_id in updated_vm_map:
                            # Use the updated version
                            merged_vms.append(updated_vm_map[vm_id])
                            # Remove from map so we don't add it again
                            del updated_vm_map[vm_id]
                        else:
                            # Keep existing VM
                            merged_vms.append(existing_vm)

                    # Add any new VMs that weren't in the existing cache
                    merged_vms.extend(updated_vm_map.values())

                    vm_list = merged_vms
            except Exception:
                logger.warning("Failed to merge partial cache update for %s, writing full update", config.id, exc_info=True)

        # Use the actual merged list count for partial updates
        vm_count = len(vm_list)

        # For partial updates, keep the original generated_at unless we have a new one
        generated_at = meta.get("generated_at") if isinstance(meta.get("generated_at"), datetime) else existing_generated_at

        payload = {
            "config": {
                "id": config.id,
                "name": config.name,
                "base_url": config.base_url,
                "username": config.username,
                "verify_ssl": config.verify_ssl,
            },
            "generated_at": _isoformat(generated_at),
            "vm_count": vm_count,
            "vms": [_serialize_vm(vm) for vm in vm_list],
        }
        try:
            path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        except Exception:
            logger.warning("Failed to write vCenter cache for %s", config.id, exc_info=True)

    def _fetch_inventory_live(
        self,
        config: VCenterConfigEntity,
        password: str,
        *,
        vm_filters: set[str] | None = None,
    ) -> tuple[list[VCenterVM], dict[str, Any]]:
        client_config = VCenterClientConfig(
            base_url=config.base_url,
            username=config.username,
            password=password,
            verify_ssl=config.verify_ssl,
        )

        vms: list[VCenterVM] = []
        metadata: dict[str, Any] = {}

        # Choose client class based on configuration
        client_cls = ESXiClient if config.is_esxi else VCenterClient
        is_esxi = config.is_esxi

        with client_cls(client_config) as client:
            summaries = client.list_vms()
            # server_guid is only available on vCenter
            server_guid = client.get_server_guid() if not is_esxi and hasattr(client, "get_server_guid") else None
            vm_payloads: list[
                tuple[
                    Mapping[str, Any],
                    Mapping[str, Any] | None,
                    list[Mapping[str, Any]],
                    Mapping[str, Any] | None,
                    tuple[str, ...] | None,
                    Mapping[str, Any] | None,
                    Mapping[str, Any] | None,
                    list[Mapping[str, Any]],
                    list[Mapping[str, Any]],
                ]
            ] = []

            host_ids: set[str] = set()
            cluster_ids: set[str] = set()
            datacenter_ids: set[str] = set()
            resource_pool_ids: set[str] = set()
            folder_ids: set[str] = set()

            for summary in summaries:
                if not isinstance(summary, Mapping):
                    continue
                vm_identifier = summary.get("vm")
                if vm_filters:
                    identifier_text = str(vm_identifier or "").strip().lower()
                    if identifier_text not in vm_filters:
                        continue
                summary_map: dict[str, Any] = dict(summary)
                detail: Mapping[str, Any] | None = None
                try:
                    detail = client.get_vm(str(vm_identifier)) if vm_identifier else None
                except VCenterAuthError:
                    raise
                except VCenterClientError:
                    logger.warning(
                        "Failed to fetch detail for VM %s on vCenter %s",
                        vm_identifier,
                        config.name,
                        exc_info=True,
                    )

                placement_info: Mapping[str, Any] | None = None
                if not is_esxi:
                    try:
                        placement_info = client.get_vm_placement(str(vm_identifier)) if vm_identifier else None
                    except VCenterClientError:
                        logger.debug(
                            "Failed to fetch placement for VM %s on vCenter %s",
                            vm_identifier,
                            config.name,
                            exc_info=True,
                        )

                instance_uuid = None
                if isinstance(detail, Mapping):
                    identity_block = detail.get("identity")
                    if isinstance(identity_block, Mapping):
                        raw_uuid = identity_block.get("instance_uuid")
                        if isinstance(raw_uuid, str) and raw_uuid.strip():
                            instance_uuid = raw_uuid.strip()

                guest_interfaces: list[Mapping[str, Any]] = []
                try:
                    guest_interfaces = client.get_vm_guest_interfaces(str(vm_identifier)) if vm_identifier else []
                except VCenterClientError:
                    logger.debug(
                        "Failed to fetch guest interfaces for VM %s on vCenter %s",
                        vm_identifier,
                        config.name,
                        exc_info=True,
                    )

                custom_attrs: Mapping[str, Any] | None = None
                if not is_esxi:
                    try:
                        custom_attrs = client.list_vm_custom_attributes(str(vm_identifier))
                    except VCenterClientError:
                        logger.debug(
                            "Failed to load custom attributes for VM %s on vCenter %s",
                            vm_identifier,
                            config.name,
                            exc_info=True,
                        )

                tag_names: tuple[str, ...] | None = None
                if not is_esxi:
                    try:
                        tag_names = client.list_vm_tags(str(vm_identifier))
                    except VCenterClientError:
                        logger.debug(
                            "Failed to load tags for VM %s on vCenter %s",
                            vm_identifier,
                            config.name,
                            exc_info=True,
                        )

                guest_identity: Mapping[str, Any] | None = None
                if not is_esxi:
                    try:
                        guest_identity = client.get_vm_guest_identity(str(vm_identifier))
                    except VCenterClientError:
                        logger.debug(
                            "Failed to load guest identity for VM %s on vCenter %s",
                            vm_identifier,
                            config.name,
                            exc_info=True,
                        )
                # ESXi client puts identity in detail response

                tools_info: Mapping[str, Any] | None = None
                if not is_esxi:
                    try:
                        tools_info = client.get_vm_tools(str(vm_identifier))
                    except VCenterClientError:
                        logger.debug(
                            "Failed to load VMware Tools info for VM %s on vCenter %s",
                            vm_identifier,
                            config.name,
                            exc_info=True,
                        )
                # ESXi client puts tools info in detail response

                snapshots: list[Mapping[str, Any]] = []
                try:
                    # For ESXi, get_vm_snapshots logic is inside the client
                    if is_esxi:
                        snapshots = client.get_vm_snapshots(str(vm_identifier))
                    else:
                        # Try REST API first
                        snapshots = client.get_vm_snapshots(str(vm_identifier))
                        # If REST API returns empty and we have instance_uuid, try pyVmomi
                        if not snapshots and instance_uuid:
                            snapshots = client.get_vm_snapshots_vim(instance_uuid)
                except VCenterClientError:
                    logger.warning(
                        "Failed to load snapshots for VM %s on vCenter %s",
                        vm_identifier,
                        config.name,
                        exc_info=True,
                    )
                except Exception:
                    logger.warning(
                        "Unexpected error loading snapshots for VM %s on vCenter %s",
                        vm_identifier,
                        config.name,
                        exc_info=True,
                    )

                disks: list[Mapping[str, Any]] = []
                try:
                    if is_esxi:
                        disks = client.get_vm_disks(str(vm_identifier))
                    else:
                        # Use pyVmomi for disks as REST API doesn't return detailed info
                        if instance_uuid:
                            disks = client.get_vm_disks_vim(instance_uuid)
                        # Fallback to REST API if pyVmomi fails
                        if not disks:
                            disks = client.get_vm_disks(str(vm_identifier))
                except VCenterClientError:
                    logger.warning(
                        "Failed to load disks for VM %s on vCenter %s",
                        vm_identifier,
                        config.name,
                        exc_info=True,
                    )
                except Exception:
                    logger.warning(
                        "Unexpected error loading disks for VM %s on vCenter %s",
                        vm_identifier,
                        config.name,
                        exc_info=True,
                    )

                placement_from_vim: Mapping[str, str] = {}
                if not is_esxi and not placement_info and instance_uuid:
                    placement_from_vim = client.get_vm_placement_vim(instance_uuid)

                detail_payload: Mapping[str, Any] | None = detail
                merged_detail: dict[str, Any] = dict(detail or {}) if detail else {}
                placement_section: dict[str, Any] = {}
                if isinstance(placement_info, Mapping):
                    placement_section = dict(placement_info)
                if placement_from_vim:
                    placement_section = dict(placement_section)
                    for key, name in placement_from_vim.items():
                        if not name:
                            continue
                        current = placement_section.get(key)
                        existing_label = None
                        if isinstance(current, Mapping):
                            existing_label = _normalize_text(current.get("name"))
                        if existing_label:
                            continue
                        placement_section[key] = {"name": name}
                        summary_map.setdefault(key, {"name": name})
                if placement_section:
                    merged_detail["placement"] = placement_section
                if merged_detail:
                    detail_payload = merged_detail

                vm_payloads.append(
                    (summary_map, detail_payload, guest_interfaces, custom_attrs, tag_names, guest_identity, tools_info, snapshots, disks)
                )

                host_ids.update(_collect_reference_ids(summary_map.get("host"), ("host",)))
                host_ids.update(_collect_reference_ids(_extract_placement_raw(detail_payload, "host"), ("host",)))
                cluster_ids.update(_collect_reference_ids(summary_map.get("cluster"), ("cluster",)))
                cluster_ids.update(_collect_reference_ids(_extract_placement_raw(detail_payload, "cluster"), ("cluster",)))
                datacenter_ids.update(_collect_reference_ids(summary_map.get("datacenter"), ("datacenter",)))
                datacenter_ids.update(
                    _collect_reference_ids(_extract_placement_raw(detail_payload, "datacenter"), ("datacenter",))
                )
                resource_pool_ids.update(
                    _collect_reference_ids(summary_map.get("resource_pool"), ("resource_pool", "pool"))
                )
                resource_pool_ids.update(
                    _collect_reference_ids(
                        _extract_placement_raw(detail_payload, "resource_pool"),
                        ("resource_pool", "pool"),
                    )
                )
                folder_ids.update(_collect_reference_ids(summary_map.get("folder"), ("folder",)))
                folder_ids.update(_collect_reference_ids(_extract_placement_raw(detail_payload, "folder"), ("folder",)))

            def _safe_lookup(name: str, loader, ids: set[str]) -> dict[str, str]:
                if not ids or is_esxi: # Skip lookups for ESXi
                    return {}
                try:
                    return loader()
                except VCenterClientError:
                    logger.debug("Failed to load %s list from vCenter", name, exc_info=True)
                    return {}

            lookups = {
                "hosts": _safe_lookup("host", client.list_hosts if not is_esxi else None, host_ids),
                "clusters": _safe_lookup("cluster", client.list_clusters if not is_esxi else None, cluster_ids),
                "datacenters": _safe_lookup("datacenter", client.list_datacenters if not is_esxi else None, datacenter_ids),
                "resource_pools": _safe_lookup("resource pool", client.list_resource_pools if not is_esxi else None, resource_pool_ids),
                "folders": _safe_lookup("folder", client.list_folders if not is_esxi else None, folder_ids),
            }

            for summary, detail, guest_interfaces, custom_attrs, tag_names, guest_identity, tools_info, snapshots, disks in vm_payloads:
                try:
                    vm = _build_vm(
                        summary,
                        detail,
                        guest_interfaces,
                        lookups,
                        custom_attrs,
                        tag_names,
                        guest_identity,
                        tools_info,
                        snapshots,
                        disks,
                        base_url=config.base_url,
                        server_guid=server_guid,
                        is_esxi=config.is_esxi,
                    )
                except Exception:
                    vm_identifier = summary.get("vm") if isinstance(summary, Mapping) else None
                    logger.exception("Failed to normalise VM %s on vCenter %s", vm_identifier, config.name)
                    continue
                vms.append(vm)

        metadata["generated_at"] = _now_utc()
        metadata["vm_count"] = len(vms)
        return vms, metadata


def create_vcenter_service(session: Session | None = None) -> VCenterService:
    """Create a VCenterService using the configured storage backend.

    Args:
        session: SQLAlchemy session (only required for SQLite backend).

    Returns:
        Configured VCenterService instance.
    """
    from infrastructure_atlas.infrastructure.repository_factory import (
        get_storage_backend,
        get_vcenter_config_repository,
    )

    backend = get_storage_backend()

    if backend == "mongodb":
        return VCenterService(
            repo=get_vcenter_config_repository(),
            session=None,
            backend="mongodb",
        )

    # SQLite backend
    if session is None:
        from infrastructure_atlas.db import get_sessionmaker

        Sessionmaker = get_sessionmaker()
        session = Sessionmaker()

    from infrastructure_atlas.infrastructure.db.repositories import SqlAlchemyVCenterConfigRepository

    return VCenterService(
        repo=SqlAlchemyVCenterConfigRepository(session),
        session=session,
        backend="sqlite",
    )


__all__ = ["VCenterService", "create_vcenter_service"]
