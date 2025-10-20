"""Generic sync framework for integrating external systems."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from infrastructure_atlas.domain.models.device import (
    Device,
    DeviceRelationship,
    SourceSystem,
    SyncMetadata,
    SyncResult,
)

logger = logging.getLogger(__name__)


class DeviceRepository(ABC):
    """Repository interface for device CRUD operations."""

    @abstractmethod
    def get_by_id(self, device_id: int) -> Device | None:
        """Get device by ID."""
        ...

    @abstractmethod
    def get_by_source(self, source_system: SourceSystem, source_id: str) -> Device | None:
        """Get device by source system and source ID."""
        ...

    @abstractmethod
    def list_by_source(self, source_system: SourceSystem) -> list[Device]:
        """List all devices from a source system."""
        ...

    @abstractmethod
    def create(self, device: Device) -> Device:
        """Create a new device."""
        ...

    @abstractmethod
    def update(self, device: Device) -> Device:
        """Update an existing device."""
        ...

    @abstractmethod
    def delete(self, device_id: int) -> None:
        """Delete a device."""
        ...

    @abstractmethod
    def mark_stale(self, source_system: SourceSystem, source_identifier: str | None, seen_ids: set[str]) -> int:
        """
        Mark devices as stale that weren't seen in this sync.

        Returns count of devices marked stale.
        """
        ...

    @abstractmethod
    def create_relationship(self, relationship: DeviceRelationship) -> DeviceRelationship:
        """Create a device relationship."""
        ...

    @abstractmethod
    def get_sync_metadata(self, source_system: SourceSystem, source_identifier: str | None) -> SyncMetadata | None:
        """Get sync metadata for a source."""
        ...

    @abstractmethod
    def update_sync_metadata(self, metadata: SyncMetadata) -> SyncMetadata:
        """Update sync metadata."""
        ...


class SyncService(ABC):
    """
    Base class for sync services.

    Provides a framework for fetching data from external systems,
    transforming to generic Device models, and loading into the database.
    """

    def __init__(self, repository: DeviceRepository, source_system: SourceSystem):
        self.repository = repository
        self.source_system = source_system
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    @abstractmethod
    def fetch(self, source_identifier: str | None = None) -> list[Mapping[str, Any]]:
        """
        Fetch raw data from the source system.

        Args:
            source_identifier: Optional identifier for specific source instance

        Returns:
            List of raw device data from the source system
        """
        ...

    @abstractmethod
    def transform(self, raw_data: Mapping[str, Any]) -> Device:
        """
        Transform raw data into a generic Device model.

        Args:
            raw_data: Raw device data from source system

        Returns:
            Device domain model
        """
        ...

    def load(self, device: Device) -> tuple[Device, bool]:
        """
        Load device into database (create or update).

        Args:
            device: Device to load

        Returns:
            Tuple of (device, is_new) where is_new is True if created
        """
        existing = self.repository.get_by_source(device.source_system, device.source_id)

        if existing:
            # Update existing device
            updated_device = Device(
                id=existing.id,
                name=device.name,
                device_type=device.device_type,
                source_system=device.source_system,
                source_id=device.source_id,
                status=device.status,
                metadata=device.metadata,
                first_seen=existing.first_seen,  # Preserve first_seen
                last_seen=datetime.now(),
                created_at=existing.created_at,
                updated_at=datetime.now(),
            )
            return self.repository.update(updated_device), False
        else:
            # Create new device
            now = datetime.now()
            new_device = Device(
                id=None,
                name=device.name,
                device_type=device.device_type,
                source_system=device.source_system,
                source_id=device.source_id,
                status=device.status,
                metadata=device.metadata,
                first_seen=now,
                last_seen=now,
                created_at=now,
                updated_at=now,
            )
            return self.repository.create(new_device), True

    def sync(self, source_identifier: str | None = None) -> SyncResult:
        """
        Execute full sync: fetch, transform, load.

        Args:
            source_identifier: Optional identifier for specific source instance

        Returns:
            SyncResult with statistics and status
        """
        start_time = datetime.now()
        result = SyncResult(
            source_system=self.source_system,
            source_identifier=source_identifier,
        )

        try:
            # Start sync metadata tracking
            sync_meta = self.repository.get_sync_metadata(self.source_system, source_identifier)
            if not sync_meta:
                sync_meta = SyncMetadata(
                    id=None,
                    source_system=self.source_system,
                    source_identifier=source_identifier,
                )

            sync_meta.last_sync_start = start_time
            sync_meta = self.repository.update_sync_metadata(sync_meta)

            self.logger.info(
                f"Starting sync for {self.source_system.value}"
                + (f" ({source_identifier})" if source_identifier else "")
            )

            # Fetch raw data
            raw_devices = self.fetch(source_identifier)
            self.logger.info(f"Fetched {len(raw_devices)} devices from {self.source_system.value}")

            # Track which source IDs we've seen
            seen_source_ids: set[str] = set()

            # Transform and load each device
            for raw_device in raw_devices:
                try:
                    device = self.transform(raw_device)
                    seen_source_ids.add(device.source_id)

                    loaded_device, is_new = self.load(device)

                    if is_new:
                        result.devices_added += 1
                    else:
                        result.devices_updated += 1

                except Exception as e:
                    self.logger.error(f"Failed to process device: {e}", exc_info=True)
                    result.devices_failed += 1

            # Mark devices not seen as stale
            stale_count = self.repository.mark_stale(self.source_system, source_identifier, seen_source_ids)
            result.devices_removed = stale_count

            # Update sync metadata
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            result.duration_seconds = duration

            sync_meta.last_sync_complete = end_time
            sync_meta.last_sync_status = "success"
            sync_meta.sync_duration_seconds = duration
            sync_meta.devices_added = result.devices_added
            sync_meta.devices_updated = result.devices_updated
            sync_meta.devices_removed = result.devices_removed
            sync_meta.error_message = None
            self.repository.update_sync_metadata(sync_meta)

            self.logger.info(f"Sync complete: {result.summary()}")
            return result

        except Exception as e:
            self.logger.error(f"Sync failed: {e}", exc_info=True)

            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()

            result.success = False
            result.error_message = str(e)
            result.duration_seconds = duration

            # Update sync metadata with error
            if sync_meta:
                sync_meta.last_sync_complete = end_time
                sync_meta.last_sync_status = "failed"
                sync_meta.sync_duration_seconds = duration
                sync_meta.error_message = str(e)
                self.repository.update_sync_metadata(sync_meta)

            return result
