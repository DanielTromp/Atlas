"""Conversion helpers between MongoDB documents and domain entities.

Provides bidirectional mapping between:
- MongoDB documents (dict-like objects)
- Domain entities (dataclasses)
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from infrastructure_atlas.domain.entities import (
    BotConversationEntity,
    BotMessageEntity,
    BotPlatformAccountEntity,
    BotWebhookConfigEntity,
    ChatMessageEntity,
    ChatSessionEntity,
    ForemanConfigEntity,
    GlobalAPIKeyEntity,
    PuppetConfigEntity,
    RolePermissionEntity,
    UserAPIKeyEntity,
    UserEntity,
    VCenterConfigEntity,
)
from infrastructure_atlas.domain.integrations import NetboxDeviceRecord, NetboxVMRecord
from infrastructure_atlas.domain.integrations.vcenter import VCenterVM


def _parse_datetime(value: Any) -> datetime | None:
    """Parse a datetime from various formats."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)
        except ValueError:
            return None
    return None


def _isoformat(dt: datetime | None) -> str | None:
    """Format a datetime to ISO format."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _now_utc() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(UTC)


# =============================================================================
# User Mappers
# =============================================================================


def user_to_document(entity: UserEntity) -> dict[str, Any]:
    """Convert a UserEntity to a MongoDB document."""
    return {
        "_id": entity.id,
        "username": entity.username,
        "display_name": entity.display_name,
        "email": entity.email,
        "role": entity.role,
        "is_active": entity.is_active,
        "created_at": entity.created_at,
        "updated_at": entity.updated_at,
    }


def document_to_user(doc: Mapping[str, Any]) -> UserEntity:
    """Convert a MongoDB document to a UserEntity."""
    return UserEntity(
        id=str(doc.get("_id") or ""),
        username=str(doc.get("username") or ""),
        display_name=doc.get("display_name"),
        email=doc.get("email"),
        role=str(doc.get("role") or "member"),
        permissions=frozenset(),
        is_active=bool(doc.get("is_active", True)),
        created_at=_parse_datetime(doc.get("created_at")) or _now_utc(),
        updated_at=_parse_datetime(doc.get("updated_at")) or _now_utc(),
    )


# =============================================================================
# User API Key Mappers
# =============================================================================


def user_api_key_to_document(entity: UserAPIKeyEntity) -> dict[str, Any]:
    """Convert a UserAPIKeyEntity to a MongoDB document."""
    return {
        "_id": entity.id,
        "user_id": entity.user_id,
        "provider": entity.provider,
        "label": entity.label,
        "secret": entity.secret,
        "created_at": entity.created_at,
        "updated_at": entity.updated_at,
    }


def document_to_user_api_key(doc: Mapping[str, Any]) -> UserAPIKeyEntity:
    """Convert a MongoDB document to a UserAPIKeyEntity."""
    return UserAPIKeyEntity(
        id=str(doc.get("_id") or ""),
        user_id=str(doc.get("user_id") or ""),
        provider=str(doc.get("provider") or ""),
        label=doc.get("label"),
        secret=str(doc.get("secret") or ""),
        created_at=_parse_datetime(doc.get("created_at")) or _now_utc(),
        updated_at=_parse_datetime(doc.get("updated_at")) or _now_utc(),
    )


# =============================================================================
# Global API Key Mappers
# =============================================================================


def global_api_key_to_document(entity: GlobalAPIKeyEntity) -> dict[str, Any]:
    """Convert a GlobalAPIKeyEntity to a MongoDB document."""
    return {
        "_id": entity.id,
        "provider": entity.provider,
        "label": entity.label,
        "secret": entity.secret,
        "created_at": entity.created_at,
        "updated_at": entity.updated_at,
    }


def document_to_global_api_key(doc: Mapping[str, Any]) -> GlobalAPIKeyEntity:
    """Convert a MongoDB document to a GlobalAPIKeyEntity."""
    return GlobalAPIKeyEntity(
        id=str(doc.get("_id") or ""),
        provider=str(doc.get("provider") or ""),
        label=doc.get("label"),
        secret=str(doc.get("secret") or ""),
        created_at=_parse_datetime(doc.get("created_at")) or _now_utc(),
        updated_at=_parse_datetime(doc.get("updated_at")) or _now_utc(),
    )


# =============================================================================
# Role Permission Mappers
# =============================================================================


def role_permission_to_document(entity: RolePermissionEntity) -> dict[str, Any]:
    """Convert a RolePermissionEntity to a MongoDB document."""
    return {
        "_id": entity.role,
        "role": entity.role,
        "label": entity.label,
        "description": entity.description,
        "permissions": list(entity.permissions),
        "created_at": entity.created_at,
        "updated_at": entity.updated_at,
    }


def document_to_role_permission(doc: Mapping[str, Any]) -> RolePermissionEntity:
    """Convert a MongoDB document to a RolePermissionEntity."""
    perms = doc.get("permissions") or []
    return RolePermissionEntity(
        role=str(doc.get("role") or doc.get("_id") or ""),
        label=str(doc.get("label") or ""),
        description=doc.get("description"),
        permissions=frozenset(perms) if perms else frozenset(),
        created_at=_parse_datetime(doc.get("created_at")) or _now_utc(),
        updated_at=_parse_datetime(doc.get("updated_at")) or _now_utc(),
    )


# =============================================================================
# Chat Session Mappers
# =============================================================================


def chat_session_to_document(entity: ChatSessionEntity) -> dict[str, Any]:
    """Convert a ChatSessionEntity to a MongoDB document."""
    return {
        "_id": entity.id,
        "session_id": entity.session_id,
        "user_id": entity.user_id,
        "title": entity.title,
        "created_at": entity.created_at,
        "updated_at": entity.updated_at,
        "context_variables": entity.context_variables,
        "agent_config_id": entity.agent_config_id,
        "provider_type": entity.provider_type,
        "model": entity.model,
    }


def document_to_chat_session(doc: Mapping[str, Any]) -> ChatSessionEntity:
    """Convert a MongoDB document to a ChatSessionEntity."""
    return ChatSessionEntity(
        id=str(doc.get("_id") or ""),
        session_id=str(doc.get("session_id") or ""),
        user_id=doc.get("user_id"),
        title=str(doc.get("title") or "New AI Chat"),
        created_at=_parse_datetime(doc.get("created_at")) or _now_utc(),
        updated_at=_parse_datetime(doc.get("updated_at")) or _now_utc(),
        context_variables=doc.get("context_variables"),
        agent_config_id=doc.get("agent_config_id"),
        provider_type=doc.get("provider_type"),
        model=doc.get("model"),
    )


# =============================================================================
# Chat Message Mappers
# =============================================================================


def chat_message_to_document(entity: ChatMessageEntity) -> dict[str, Any]:
    """Convert a ChatMessageEntity to a MongoDB document."""
    return {
        "_id": entity.id,
        "session_id": entity.session_id,
        "role": entity.role,
        "content": entity.content,
        "created_at": entity.created_at,
        "message_type": entity.message_type,
        "tool_call_id": entity.tool_call_id,
        "tool_name": entity.tool_name,
        "metadata_json": entity.metadata_json,
    }


def document_to_chat_message(doc: Mapping[str, Any]) -> ChatMessageEntity:
    """Convert a MongoDB document to a ChatMessageEntity."""
    return ChatMessageEntity(
        id=str(doc.get("_id") or ""),
        session_id=str(doc.get("session_id") or ""),
        role=str(doc.get("role") or "user"),
        content=str(doc.get("content") or ""),
        created_at=_parse_datetime(doc.get("created_at")) or _now_utc(),
        message_type=doc.get("message_type"),
        tool_call_id=doc.get("tool_call_id"),
        tool_name=doc.get("tool_name"),
        metadata_json=doc.get("metadata_json"),
    )


# =============================================================================
# VCenter Config Mappers
# =============================================================================


def vcenter_config_to_document(entity: VCenterConfigEntity) -> dict[str, Any]:
    """Convert a VCenterConfigEntity to a MongoDB document."""
    return {
        "_id": entity.id,
        "name": entity.name,
        "base_url": entity.base_url,
        "username": entity.username,
        "verify_ssl": entity.verify_ssl,
        "is_esxi": entity.is_esxi,
        "password_secret": entity.password_secret,
        "created_at": entity.created_at,
        "updated_at": entity.updated_at,
    }


def document_to_vcenter_config(doc: Mapping[str, Any]) -> VCenterConfigEntity:
    """Convert a MongoDB document to a VCenterConfigEntity."""
    return VCenterConfigEntity(
        id=str(doc.get("_id") or ""),
        name=str(doc.get("name") or ""),
        base_url=str(doc.get("base_url") or ""),
        username=str(doc.get("username") or ""),
        verify_ssl=bool(doc.get("verify_ssl", True)),
        is_esxi=bool(doc.get("is_esxi", False)),
        password_secret=str(doc.get("password_secret") or ""),
        created_at=_parse_datetime(doc.get("created_at")) or _now_utc(),
        updated_at=_parse_datetime(doc.get("updated_at")) or _now_utc(),
    )


# =============================================================================
# Foreman Config Mappers
# =============================================================================


def foreman_config_to_document(entity: ForemanConfigEntity) -> dict[str, Any]:
    """Convert a ForemanConfigEntity to a MongoDB document."""
    return {
        "_id": entity.id,
        "name": entity.name,
        "base_url": entity.base_url,
        "username": entity.username,
        "token_secret": entity.token_secret,
        "verify_ssl": entity.verify_ssl,
        "created_at": entity.created_at,
        "updated_at": entity.updated_at,
    }


def document_to_foreman_config(doc: Mapping[str, Any]) -> ForemanConfigEntity:
    """Convert a MongoDB document to a ForemanConfigEntity."""
    return ForemanConfigEntity(
        id=str(doc.get("_id") or ""),
        name=str(doc.get("name") or ""),
        base_url=str(doc.get("base_url") or ""),
        username=str(doc.get("username") or ""),
        token_secret=str(doc.get("token_secret") or ""),
        verify_ssl=bool(doc.get("verify_ssl", True)),
        created_at=_parse_datetime(doc.get("created_at")) or _now_utc(),
        updated_at=_parse_datetime(doc.get("updated_at")) or _now_utc(),
    )


# =============================================================================
# Puppet Config Mappers
# =============================================================================


def puppet_config_to_document(entity: PuppetConfigEntity) -> dict[str, Any]:
    """Convert a PuppetConfigEntity to a MongoDB document."""
    return {
        "_id": entity.id,
        "name": entity.name,
        "remote_url": entity.remote_url,
        "branch": entity.branch,
        "ssh_key_secret": entity.ssh_key_secret,
        "local_path": entity.local_path,
        "created_at": entity.created_at,
        "updated_at": entity.updated_at,
    }


def document_to_puppet_config(doc: Mapping[str, Any]) -> PuppetConfigEntity:
    """Convert a MongoDB document to a PuppetConfigEntity."""
    return PuppetConfigEntity(
        id=str(doc.get("_id") or ""),
        name=str(doc.get("name") or ""),
        remote_url=str(doc.get("remote_url") or ""),
        branch=str(doc.get("branch") or "production"),
        ssh_key_secret=doc.get("ssh_key_secret"),
        local_path=doc.get("local_path"),
        created_at=_parse_datetime(doc.get("created_at")) or _now_utc(),
        updated_at=_parse_datetime(doc.get("updated_at")) or _now_utc(),
    )


# =============================================================================
# VCenter VM Cache Mappers
# =============================================================================


def vcenter_vm_to_document(vm: VCenterVM, config_id: str) -> dict[str, Any]:
    """Convert a VCenterVM to a MongoDB cache document.

    Args:
        vm: The VCenterVM domain entity.
        config_id: The vCenter configuration ID this VM belongs to.

    Returns:
        A MongoDB document with config_id:vm_id as the primary key.
    """
    return {
        "_id": f"{config_id}:{vm.vm_id}",
        "config_id": config_id,
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
        "updated_at": _now_utc(),
    }


def document_to_vcenter_vm(doc: Mapping[str, Any]) -> VCenterVM:
    """Convert a MongoDB cache document to a VCenterVM."""
    raw_attrs = doc.get("custom_attributes")
    custom_attributes: dict[str, str] = {}
    if isinstance(raw_attrs, Mapping):
        for key, value in raw_attrs.items():
            if isinstance(key, str):
                custom_attributes[key] = str(value) if value is not None else ""

    raw_tags = doc.get("tags") or ()
    tag_tuple = tuple(str(tag).strip() for tag in raw_tags if isinstance(tag, str) and tag.strip())

    raw_networks = doc.get("network_names") or ()
    network_names = tuple(str(item).strip() for item in raw_networks if isinstance(item, str) and item.strip())

    raw_snapshots = doc.get("snapshots") or []
    snapshot_tuple = tuple(dict(s) for s in raw_snapshots if isinstance(s, Mapping))

    raw_disks = doc.get("disks") or []
    disk_tuple = tuple(dict(d) for d in raw_disks if isinstance(d, Mapping))

    tools_version = doc.get("tools_version")
    if isinstance(tools_version, int | float):
        tools_version = str(tools_version)
    elif isinstance(tools_version, str):
        tools_version = tools_version.strip() or None

    auto_update_raw = doc.get("tools_auto_update_supported")
    tools_auto_update_supported = auto_update_raw if isinstance(auto_update_raw, bool) else None

    def _safe_int(value: Any) -> int | None:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, float):
            return round(value)
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
        return None

    return VCenterVM(
        vm_id=str(doc.get("vm_id") or ""),
        name=str(doc.get("name") or ""),
        power_state=doc.get("power_state"),
        cpu_count=_safe_int(doc.get("cpu_count")),
        memory_mib=_safe_int(doc.get("memory_mib")),
        guest_os=doc.get("guest_os"),
        tools_status=doc.get("tools_status"),
        hardware_version=doc.get("hardware_version"),
        is_template=doc.get("is_template") if isinstance(doc.get("is_template"), bool) else None,
        instance_uuid=doc.get("instance_uuid"),
        bios_uuid=doc.get("bios_uuid"),
        ip_addresses=tuple(str(v).strip() for v in (doc.get("ip_addresses") or []) if isinstance(v, str) and v.strip()),
        mac_addresses=tuple(
            str(v).strip().lower() for v in (doc.get("mac_addresses") or []) if isinstance(v, str) and v.strip()
        ),
        host=doc.get("host"),
        cluster=doc.get("cluster"),
        datacenter=doc.get("datacenter"),
        resource_pool=doc.get("resource_pool"),
        folder=doc.get("folder"),
        guest_family=doc.get("guest_family"),
        guest_name=doc.get("guest_name"),
        guest_full_name=doc.get("guest_full_name"),
        guest_host_name=doc.get("guest_host_name"),
        guest_ip_address=doc.get("guest_ip_address"),
        tools_run_state=doc.get("tools_run_state"),
        tools_version=tools_version,
        tools_version_status=doc.get("tools_version_status"),
        tools_install_type=doc.get("tools_install_type"),
        tools_auto_update_supported=tools_auto_update_supported,
        vcenter_url=doc.get("vcenter_url"),
        network_names=network_names,
        custom_attributes=custom_attributes,
        tags=tag_tuple,
        snapshots=snapshot_tuple,
        snapshot_count=_safe_int(doc.get("snapshot_count")),
        disks=disk_tuple,
        total_disk_capacity_bytes=_safe_int(doc.get("total_disk_capacity_bytes")),
        total_provisioned_bytes=_safe_int(doc.get("total_provisioned_bytes")),
        raw_summary=None,
        raw_detail=None,
    )


# =============================================================================
# NetBox Device Cache Mappers
# =============================================================================


def netbox_device_to_document(record: NetboxDeviceRecord) -> dict[str, Any]:
    """Convert a NetboxDeviceRecord to a MongoDB cache document."""
    return {
        "_id": f"netbox_device_{record.id}",
        "netbox_id": int(record.id),
        "name": record.name,
        "status": record.status,
        "status_label": record.status_label,
        "role": record.role,
        "tenant": record.tenant,
        "tenant_group": record.tenant_group,
        "site": record.site,
        "location": record.location,
        "cluster": record.cluster,
        "primary_ip": record.primary_ip,
        "primary_ip4": record.primary_ip4,
        "primary_ip6": record.primary_ip6,
        "oob_ip": record.oob_ip,
        "tags": list(record.tags),
        "last_updated": record.last_updated,
        "custom_fields": record.custom_fields,
        "manufacturer": record.manufacturer,
        "model": record.model,
        "rack": record.rack,
        "rack_unit": record.rack_unit,
        "serial": record.serial,
        "asset_tag": record.asset_tag,
        "site_group": record.site_group,
        "region": record.region,
        "description": record.description,
        "raw": record.raw,
        "cached_at": _now_utc(),
    }


def document_to_netbox_device(doc: Mapping[str, Any]) -> NetboxDeviceRecord:
    """Convert a MongoDB cache document to a NetboxDeviceRecord."""
    tags = doc.get("tags") or ()
    return NetboxDeviceRecord(
        id=int(doc.get("netbox_id") or 0),
        name=str(doc.get("name") or ""),
        status=doc.get("status"),
        status_label=doc.get("status_label"),
        role=doc.get("role"),
        tenant=doc.get("tenant"),
        tenant_group=doc.get("tenant_group"),
        site=doc.get("site"),
        location=doc.get("location"),
        cluster=doc.get("cluster"),
        primary_ip=doc.get("primary_ip"),
        primary_ip4=doc.get("primary_ip4"),
        primary_ip6=doc.get("primary_ip6"),
        oob_ip=doc.get("oob_ip"),
        tags=tuple(tags) if not isinstance(tags, tuple) else tags,
        last_updated=_parse_datetime(doc.get("last_updated")),
        custom_fields=doc.get("custom_fields") or {},
        raw=doc.get("raw") or {},
        source=None,
        manufacturer=doc.get("manufacturer"),
        model=doc.get("model"),
        rack=doc.get("rack"),
        rack_unit=doc.get("rack_unit"),
        serial=doc.get("serial"),
        asset_tag=doc.get("asset_tag"),
        site_group=doc.get("site_group"),
        region=doc.get("region"),
        description=doc.get("description"),
    )


# =============================================================================
# NetBox VM Cache Mappers
# =============================================================================


def netbox_vm_to_document(record: NetboxVMRecord) -> dict[str, Any]:
    """Convert a NetboxVMRecord to a MongoDB cache document."""
    return {
        "_id": f"netbox_vm_{record.id}",
        "netbox_id": int(record.id),
        "name": record.name,
        "status": record.status,
        "status_label": record.status_label,
        "role": record.role,
        "tenant": record.tenant,
        "tenant_group": record.tenant_group,
        "site": record.site,
        "location": record.location,
        "cluster": record.cluster,
        "primary_ip": record.primary_ip,
        "primary_ip4": record.primary_ip4,
        "primary_ip6": record.primary_ip6,
        "oob_ip": record.oob_ip,
        "tags": list(record.tags),
        "last_updated": record.last_updated,
        "custom_fields": record.custom_fields,
        "platform": record.platform,
        "role_detail": record.role_detail,
        "description": record.description,
        "raw": record.raw,
        "cached_at": _now_utc(),
    }


def document_to_netbox_vm(doc: Mapping[str, Any]) -> NetboxVMRecord:
    """Convert a MongoDB cache document to a NetboxVMRecord."""
    tags = doc.get("tags") or ()
    return NetboxVMRecord(
        id=int(doc.get("netbox_id") or 0),
        name=str(doc.get("name") or ""),
        status=doc.get("status"),
        status_label=doc.get("status_label"),
        role=doc.get("role"),
        tenant=doc.get("tenant"),
        tenant_group=doc.get("tenant_group"),
        site=doc.get("site"),
        location=doc.get("location"),
        cluster=doc.get("cluster"),
        primary_ip=doc.get("primary_ip"),
        primary_ip4=doc.get("primary_ip4"),
        primary_ip6=doc.get("primary_ip6"),
        oob_ip=doc.get("oob_ip"),
        tags=tuple(tags) if not isinstance(tags, tuple) else tags,
        last_updated=_parse_datetime(doc.get("last_updated")),
        custom_fields=doc.get("custom_fields") or {},
        raw=doc.get("raw") or {},
        source=None,
        platform=doc.get("platform"),
        role_detail=doc.get("role_detail"),
        description=doc.get("description"),
    )


# ---------------------------------------------------------------------------
# Bot Platform Account Mappers
# ---------------------------------------------------------------------------


def bot_platform_account_to_document(entity: BotPlatformAccountEntity) -> dict[str, Any]:
    """Convert BotPlatformAccountEntity to MongoDB document."""
    return {
        "_id": entity.id,
        "user_id": entity.user_id,
        "platform": entity.platform,
        "platform_user_id": entity.platform_user_id,
        "platform_username": entity.platform_username,
        "verified": entity.verified,
        "verification_code": entity.verification_code,
        "verification_expires": entity.verification_expires,
        "created_at": entity.created_at,
        "updated_at": entity.updated_at,
    }


def document_to_bot_platform_account(doc: Mapping[str, Any]) -> BotPlatformAccountEntity:
    """Convert MongoDB document to BotPlatformAccountEntity."""
    return BotPlatformAccountEntity(
        id=doc["_id"],
        user_id=doc["user_id"],
        platform=doc["platform"],
        platform_user_id=doc["platform_user_id"],
        platform_username=doc.get("platform_username"),
        verified=doc.get("verified", False),
        verification_code=doc.get("verification_code"),
        verification_expires=_parse_datetime(doc.get("verification_expires")),
        created_at=_parse_datetime(doc.get("created_at")) or datetime.now(UTC),
        updated_at=_parse_datetime(doc.get("updated_at")) or datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Bot Conversation Mappers
# ---------------------------------------------------------------------------


def bot_conversation_to_document(entity: BotConversationEntity) -> dict[str, Any]:
    """Convert BotConversationEntity to MongoDB document."""
    return {
        "_id": entity.id,
        "platform": entity.platform,
        "platform_conversation_id": entity.platform_conversation_id,
        "platform_account_id": entity.platform_account_id,
        "agent_id": entity.agent_id,
        "session_id": entity.session_id,
        "created_at": entity.created_at,
        "last_message_at": entity.last_message_at,
    }


def document_to_bot_conversation(doc: Mapping[str, Any]) -> BotConversationEntity:
    """Convert MongoDB document to BotConversationEntity."""
    return BotConversationEntity(
        id=doc["_id"],
        platform=doc["platform"],
        platform_conversation_id=doc["platform_conversation_id"],
        platform_account_id=doc["platform_account_id"],
        agent_id=doc.get("agent_id"),
        session_id=doc.get("session_id"),
        created_at=_parse_datetime(doc.get("created_at")) or datetime.now(UTC),
        last_message_at=_parse_datetime(doc.get("last_message_at")) or datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Bot Message Mappers
# ---------------------------------------------------------------------------


def bot_message_to_document(entity: BotMessageEntity) -> dict[str, Any]:
    """Convert BotMessageEntity to MongoDB document."""
    return {
        "_id": entity.id,
        "conversation_id": entity.conversation_id,
        "direction": entity.direction,
        "content": entity.content,
        "platform_message_id": entity.platform_message_id,
        "agent_id": entity.agent_id,
        "tool_calls": entity.tool_calls,
        "input_tokens": entity.input_tokens,
        "output_tokens": entity.output_tokens,
        "cost_usd": entity.cost_usd,
        "duration_ms": entity.duration_ms,
        "created_at": entity.created_at,
    }


def document_to_bot_message(doc: Mapping[str, Any]) -> BotMessageEntity:
    """Convert MongoDB document to BotMessageEntity."""
    return BotMessageEntity(
        id=doc["_id"],
        conversation_id=doc["conversation_id"],
        direction=doc["direction"],
        content=doc["content"],
        platform_message_id=doc.get("platform_message_id"),
        agent_id=doc.get("agent_id"),
        tool_calls=doc.get("tool_calls"),
        input_tokens=doc.get("input_tokens", 0),
        output_tokens=doc.get("output_tokens", 0),
        cost_usd=doc.get("cost_usd"),
        duration_ms=doc.get("duration_ms"),
        created_at=_parse_datetime(doc.get("created_at")) or datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Bot Webhook Config Mappers
# ---------------------------------------------------------------------------


def bot_webhook_config_to_document(entity: BotWebhookConfigEntity) -> dict[str, Any]:
    """Convert BotWebhookConfigEntity to MongoDB document."""
    return {
        "_id": entity.id,
        "platform": entity.platform,
        "enabled": entity.enabled,
        "webhook_secret": entity.webhook_secret,
        "bot_token_secret": entity.bot_token_secret,
        "extra_config": entity.extra_config,
        "created_at": entity.created_at,
        "updated_at": entity.updated_at,
    }


def document_to_bot_webhook_config(doc: Mapping[str, Any]) -> BotWebhookConfigEntity:
    """Convert MongoDB document to BotWebhookConfigEntity."""
    return BotWebhookConfigEntity(
        id=doc["_id"],
        platform=doc["platform"],
        enabled=doc.get("enabled", True),
        webhook_secret=doc.get("webhook_secret"),
        bot_token_secret=doc["bot_token_secret"],
        extra_config=doc.get("extra_config"),
        created_at=_parse_datetime(doc.get("created_at")) or datetime.now(UTC),
        updated_at=_parse_datetime(doc.get("updated_at")) or datetime.now(UTC),
    )


__all__ = [
    # User mappers
    "user_to_document",
    "document_to_user",
    # User API key mappers
    "user_api_key_to_document",
    "document_to_user_api_key",
    # Global API key mappers
    "global_api_key_to_document",
    "document_to_global_api_key",
    # Role permission mappers
    "role_permission_to_document",
    "document_to_role_permission",
    # Chat session mappers
    "chat_session_to_document",
    "document_to_chat_session",
    # Chat message mappers
    "chat_message_to_document",
    "document_to_chat_message",
    # VCenter config mappers
    "vcenter_config_to_document",
    "document_to_vcenter_config",
    # Foreman config mappers
    "foreman_config_to_document",
    "document_to_foreman_config",
    # Puppet config mappers
    "puppet_config_to_document",
    "document_to_puppet_config",
    # VCenter VM cache mappers
    "vcenter_vm_to_document",
    "document_to_vcenter_vm",
    # NetBox device cache mappers
    "netbox_device_to_document",
    "document_to_netbox_device",
    # NetBox VM cache mappers
    "netbox_vm_to_document",
    "document_to_netbox_vm",
    # Bot platform account mappers
    "bot_platform_account_to_document",
    "document_to_bot_platform_account",
    # Bot conversation mappers
    "bot_conversation_to_document",
    "document_to_bot_conversation",
    # Bot message mappers
    "bot_message_to_document",
    "document_to_bot_message",
    # Bot webhook config mappers
    "bot_webhook_config_to_document",
    "document_to_bot_webhook_config",
]
