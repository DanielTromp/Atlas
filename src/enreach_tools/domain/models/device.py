"""Generic device models for unified infrastructure representation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping


class DeviceType(str, Enum):
    """Type of infrastructure device."""

    SERVER = "server"
    VM = "vm"
    NETWORK_DEVICE = "network_device"
    STORAGE = "storage"
    CONTAINER = "container"
    UNKNOWN = "unknown"


class SourceSystem(str, Enum):
    """Source system that provided the device data."""

    VCENTER = "vcenter"
    FOREMAN = "foreman"
    PUPPET = "puppet"
    OXIDIZED = "oxidized"
    DORADO = "dorado"
    NETAPP = "netapp"
    NETBOX = "netbox"
    COMMVAULT = "commvault"
    UNKNOWN = "unknown"


class DeviceStatus(str, Enum):
    """Status of the device."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    UNKNOWN = "unknown"


class RelationshipType(str, Enum):
    """Type of relationship between devices."""

    HOSTS = "hosts"  # Parent hosts child (e.g., ESXi host hosts VM)
    CONNECTS_TO = "connects_to"  # Network connection
    BACKS_UP = "backs_up"  # Backup relationship
    MANAGES = "manages"  # Management relationship
    STORES_ON = "stores_on"  # Storage relationship
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Device:
    """
    Generic device model representing any infrastructure component.

    This model can represent VMs, servers, network devices, storage systems,
    and any other infrastructure component from any source system.
    """

    id: int | None
    name: str
    device_type: DeviceType
    source_system: SourceSystem
    source_id: str
    status: DeviceStatus = DeviceStatus.UNKNOWN
    metadata: Mapping[str, Any] = field(default_factory=dict)
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate device data."""
        if not self.name:
            raise ValueError("Device name cannot be empty")
        if not self.source_id:
            raise ValueError("Device source_id cannot be empty")

        # Validate metadata is a dict
        if not isinstance(self.metadata, (dict, Mapping)):
            raise ValueError("Device metadata must be a dictionary")


@dataclass(frozen=True)
class DeviceRelationship:
    """
    Relationship between two devices.

    Examples:
    - ESXi host (parent) hosts VM (child)
    - Server (parent) connects_to switch (child)
    - Storage array (parent) stores volume (child)
    """

    id: int | None
    parent_device_id: int
    child_device_id: int
    relationship_type: RelationshipType
    metadata: Mapping[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate relationship data."""
        if self.parent_device_id == self.child_device_id:
            raise ValueError("Device cannot have a relationship with itself")


@dataclass
class SyncMetadata:
    """
    Metadata about sync operations for a source system.

    Tracks when data was last synced, status, and statistics.
    """

    id: int | None
    source_system: SourceSystem
    source_identifier: str | None = None
    last_sync_start: datetime | None = None
    last_sync_complete: datetime | None = None
    last_sync_status: str | None = None
    sync_duration_seconds: float | None = None
    devices_added: int = 0
    devices_updated: int = 0
    devices_removed: int = 0
    error_message: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class SyncResult:
    """Result of a sync operation."""

    source_system: SourceSystem
    source_identifier: str | None
    devices_added: int = 0
    devices_updated: int = 0
    devices_removed: int = 0
    devices_failed: int = 0
    success: bool = True
    error_message: str | None = None
    duration_seconds: float | None = None

    @property
    def total_processed(self) -> int:
        """Total devices processed."""
        return self.devices_added + self.devices_updated + self.devices_removed

    def summary(self) -> str:
        """Human-readable summary of sync result."""
        if not self.success:
            return f"Sync failed: {self.error_message}"

        parts = []
        if self.devices_added:
            parts.append(f"{self.devices_added} added")
        if self.devices_updated:
            parts.append(f"{self.devices_updated} updated")
        if self.devices_removed:
            parts.append(f"{self.devices_removed} removed")
        if self.devices_failed:
            parts.append(f"{self.devices_failed} failed")

        if not parts:
            return "No changes"

        result = ", ".join(parts)
        if self.duration_seconds:
            result += f" ({self.duration_seconds:.1f}s)"

        return result
