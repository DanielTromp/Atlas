"""DTO helpers for vCenter configuration and inventory."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from enreach_tools.application.dto.base import DomainModel
from enreach_tools.domain.entities import VCenterConfigEntity
from enreach_tools.domain.integrations.vcenter import VCenterVM


class VCenterConfigDTO(DomainModel):
    id: str
    name: str
    base_url: str
    username: str
    verify_ssl: bool
    has_credentials: bool
    last_refresh: datetime | None = None
    vm_count: int | None = None
    created_at: datetime
    updated_at: datetime


class VCenterVMDTO(DomainModel):
    id: str
    name: str
    power_state: str | None = None
    cpu_count: int | None = None
    memory_mib: int | None = None
    guest_os: str | None = None
    tools_status: str | None = None
    hardware_version: str | None = None
    is_template: bool | None = None
    instance_uuid: str | None = None
    bios_uuid: str | None = None
    ip_addresses: tuple[str, ...] = ()
    mac_addresses: tuple[str, ...] = ()
    host: str | None = None
    cluster: str | None = None
    datacenter: str | None = None
    resource_pool: str | None = None
    folder: str | None = None
    custom_attributes: Mapping[str, Any] | None = None
    tags: tuple[str, ...] = ()
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
    network_names: tuple[str, ...] = ()
    summary: Mapping[str, object] | None = None
    detail: Mapping[str, object] | None = None


def vcenter_config_to_dto(
    entity: VCenterConfigEntity,
    *,
    has_credentials: bool | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> VCenterConfigDTO:
    last_refresh = None
    vm_count = None
    if metadata:
        candidate = metadata.get("generated_at")
        if isinstance(candidate, datetime):
            last_refresh = candidate
        candidate_count = metadata.get("vm_count")
        if isinstance(candidate_count, int):
            vm_count = candidate_count
    return VCenterConfigDTO(
        id=entity.id,
        name=entity.name,
        base_url=entity.base_url,
        username=entity.username,
        verify_ssl=entity.verify_ssl,
        has_credentials=bool(has_credentials if has_credentials is not None else entity.password_secret),
        last_refresh=last_refresh,
        vm_count=vm_count,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def vcenter_configs_to_dto(
    entries: Iterable[tuple[VCenterConfigEntity, Mapping[str, Any] | None]] | Iterable[VCenterConfigEntity],
) -> list[VCenterConfigDTO]:
    output: list[VCenterConfigDTO] = []
    for item in entries:
        if isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], VCenterConfigEntity):
            entity, meta = item
            output.append(vcenter_config_to_dto(entity, metadata=meta))
        elif isinstance(item, VCenterConfigEntity):
            output.append(vcenter_config_to_dto(item))
    return output


def vcenter_vm_to_dto(record: VCenterVM) -> VCenterVMDTO:
    return VCenterVMDTO(
        id=record.vm_id,
        name=record.name,
        power_state=record.power_state,
        cpu_count=record.cpu_count,
        memory_mib=record.memory_mib,
        guest_os=record.guest_os,
        tools_status=record.tools_status,
        hardware_version=record.hardware_version,
        is_template=record.is_template,
        instance_uuid=record.instance_uuid,
        bios_uuid=record.bios_uuid,
        ip_addresses=record.ip_addresses,
        mac_addresses=record.mac_addresses,
        host=record.host,
        cluster=record.cluster,
        datacenter=record.datacenter,
        resource_pool=record.resource_pool,
        folder=record.folder,
        custom_attributes=record.custom_attributes,
        tags=record.tags,
        guest_family=record.guest_family,
        guest_name=record.guest_name,
        guest_full_name=record.guest_full_name,
        guest_host_name=record.guest_host_name,
        guest_ip_address=record.guest_ip_address,
        tools_run_state=record.tools_run_state,
        tools_version=record.tools_version,
        tools_version_status=record.tools_version_status,
        tools_install_type=record.tools_install_type,
        tools_auto_update_supported=record.tools_auto_update_supported,
        vcenter_url=record.vcenter_url,
        network_names=record.network_names,
        summary=record.raw_summary,
        detail=record.raw_detail,
    )


def vcenter_vms_to_dto(records: Iterable[VCenterVM]) -> list[VCenterVMDTO]:
    return [vcenter_vm_to_dto(record) for record in records]


__all__ = [
    "VCenterConfigDTO",
    "VCenterVMDTO",
    "vcenter_config_to_dto",
    "vcenter_configs_to_dto",
    "vcenter_vm_to_dto",
    "vcenter_vms_to_dto",
]
