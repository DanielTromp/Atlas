"""MongoDB cache repositories for infrastructure data.

Provides document-level updates instead of full file rewrites, solving
the IO contention issues with concurrent agent/MCP access.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.operations import ReplaceOne

from infrastructure_atlas.domain.integrations import NetboxDeviceRecord, NetboxVMRecord
from infrastructure_atlas.domain.integrations.vcenter import VCenterVM
from infrastructure_atlas.infrastructure.logging import get_logger

from . import mappers

logger = get_logger(__name__)


def _now_utc() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(UTC)


class MongoDBVCenterCacheRepository:
    """MongoDB cache repository for vCenter VM inventory.

    Key benefit: Document-level updates instead of full JSON file rewrites.
    Each VM is stored as a separate document, allowing concurrent updates.
    """

    def __init__(self, db: Database) -> None:
        self._collection: Collection = db["vcenter_vms"]

    def get_vm(self, config_id: str, vm_id: str) -> VCenterVM | None:
        """Get a single VM by config and VM ID."""
        doc = self._collection.find_one({"config_id": config_id, "vm_id": vm_id})
        return mappers.document_to_vcenter_vm(doc) if doc else None

    def list_vms(self, config_id: str) -> list[VCenterVM]:
        """List all VMs for a vCenter configuration."""
        cursor = self._collection.find({"config_id": config_id}).sort("name", 1)
        return [mappers.document_to_vcenter_vm(doc) for doc in cursor]

    def get_vm_count(self, config_id: str) -> int:
        """Get the count of VMs for a vCenter configuration."""
        return self._collection.count_documents({"config_id": config_id})

    def upsert_vm(self, config_id: str, vm: VCenterVM) -> None:
        """Insert or update a single VM (atomic operation)."""
        doc = mappers.vcenter_vm_to_document(vm, config_id)
        self._collection.replace_one(
            {"_id": doc["_id"]},
            doc,
            upsert=True,
        )

    def upsert_vms(self, config_id: str, vms: Iterable[VCenterVM]) -> int:
        """Insert or update multiple VMs (bulk operation).

        Args:
            config_id: The vCenter configuration ID.
            vms: The VMs to upsert.

        Returns:
            The number of VMs upserted.
        """
        operations = []
        for vm in vms:
            doc = mappers.vcenter_vm_to_document(vm, config_id)
            operations.append(
                ReplaceOne(
                    {"_id": doc["_id"]},
                    doc,
                    upsert=True,
                )
            )

        if not operations:
            return 0

        result = self._collection.bulk_write(operations, ordered=False)
        return result.upserted_count + result.modified_count

    def delete_vm(self, config_id: str, vm_id: str) -> bool:
        """Delete a single VM."""
        result = self._collection.delete_one({"config_id": config_id, "vm_id": vm_id})
        return result.deleted_count > 0

    def delete_vms_for_config(self, config_id: str) -> int:
        """Delete all VMs for a vCenter configuration.

        Returns:
            The number of VMs deleted.
        """
        result = self._collection.delete_many({"config_id": config_id})
        return result.deleted_count

    def replace_all_vms(self, config_id: str, vms: Iterable[VCenterVM]) -> dict[str, int]:
        """Replace all VMs for a configuration (full refresh).

        This is a two-step operation:
        1. Delete all existing VMs for the config
        2. Insert the new VMs

        Args:
            config_id: The vCenter configuration ID.
            vms: The new VMs to insert.

        Returns:
            Dict with 'deleted' and 'inserted' counts.
        """
        vm_list = list(vms)
        deleted = self.delete_vms_for_config(config_id)

        if not vm_list:
            return {"deleted": deleted, "inserted": 0}

        documents = [mappers.vcenter_vm_to_document(vm, config_id) for vm in vm_list]
        self._collection.insert_many(documents, ordered=False)

        return {"deleted": deleted, "inserted": len(documents)}

    def search_vms(
        self,
        config_id: str | None = None,
        name_pattern: str | None = None,
        ip_address: str | None = None,
        power_state: str | None = None,
        limit: int = 100,
    ) -> list[VCenterVM]:
        """Search VMs with various filters.

        Args:
            config_id: Filter by vCenter configuration.
            name_pattern: Regex pattern for VM name.
            ip_address: Filter by IP address (exact match in array).
            power_state: Filter by power state.
            limit: Maximum results to return.

        Returns:
            List of matching VMs.
        """
        query: dict[str, Any] = {}
        if config_id:
            query["config_id"] = config_id
        if name_pattern:
            query["name"] = {"$regex": name_pattern, "$options": "i"}
        if ip_address:
            query["ip_addresses"] = ip_address
        if power_state:
            query["power_state"] = power_state.upper()

        cursor = self._collection.find(query).limit(limit).sort("name", 1)
        return [mappers.document_to_vcenter_vm(doc) for doc in cursor]

    def get_cache_metadata(self, config_id: str) -> dict[str, Any] | None:
        """Get cache metadata for a configuration.

        Returns metadata about the cached VMs including count and last update time.
        """
        pipeline = [
            {"$match": {"config_id": config_id}},
            {
                "$group": {
                    "_id": "$config_id",
                    "vm_count": {"$sum": 1},
                    "last_updated": {"$max": "$updated_at"},
                }
            },
        ]
        results = list(self._collection.aggregate(pipeline))
        if not results:
            return None
        result = results[0]
        return {
            "config_id": config_id,
            "vm_count": result.get("vm_count", 0),
            "generated_at": result.get("last_updated"),
        }


class MongoDBNetBoxCacheRepository:
    """MongoDB cache repository for NetBox devices and VMs.

    Provides document-level updates with hash-based delta detection.
    """

    def __init__(self, db: Database) -> None:
        self._devices: Collection = db["netbox_devices"]
        self._vms: Collection = db["netbox_vms"]

    # -------------------------------------------------------------------------
    # Device Operations
    # -------------------------------------------------------------------------

    def get_device(self, netbox_id: int) -> NetboxDeviceRecord | None:
        """Get a device by NetBox ID."""
        doc = self._devices.find_one({"netbox_id": netbox_id})
        return mappers.document_to_netbox_device(doc) if doc else None

    def list_devices(self, limit: int | None = None) -> list[NetboxDeviceRecord]:
        """List all devices."""
        cursor = self._devices.find().sort("name", 1)
        if limit:
            cursor = cursor.limit(limit)
        return [mappers.document_to_netbox_device(doc) for doc in cursor]

    def get_device_count(self) -> int:
        """Get the total device count."""
        return self._devices.count_documents({})

    def upsert_device(self, record: NetboxDeviceRecord) -> None:
        """Insert or update a device."""
        doc = mappers.netbox_device_to_document(record)
        self._devices.replace_one(
            {"_id": doc["_id"]},
            doc,
            upsert=True,
        )

    def upsert_devices(self, records: Iterable[NetboxDeviceRecord]) -> int:
        """Bulk upsert devices.

        Returns:
            The number of devices upserted.
        """
        operations = []
        for record in records:
            doc = mappers.netbox_device_to_document(record)
            operations.append(
                ReplaceOne(
                    {"_id": doc["_id"]},
                    doc,
                    upsert=True,
                )
            )

        if not operations:
            return 0

        result = self._devices.bulk_write(operations, ordered=False)
        return result.upserted_count + result.modified_count

    def delete_device(self, netbox_id: int) -> bool:
        """Delete a device."""
        result = self._devices.delete_one({"netbox_id": netbox_id})
        return result.deleted_count > 0

    def delete_devices_not_in(self, netbox_ids: set[int]) -> int:
        """Delete devices not in the provided set of IDs.

        Useful for removing stale devices after a sync.

        Returns:
            The number of devices deleted.
        """
        if not netbox_ids:
            return 0
        result = self._devices.delete_many({"netbox_id": {"$nin": list(netbox_ids)}})
        return result.deleted_count

    def search_devices(
        self,
        name_pattern: str | None = None,
        primary_ip: str | None = None,
        site: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[NetboxDeviceRecord]:
        """Search devices with various filters."""
        query: dict[str, Any] = {}
        if name_pattern:
            query["name"] = {"$regex": name_pattern, "$options": "i"}
        if primary_ip:
            query["primary_ip"] = primary_ip
        if site:
            query["site"] = site
        if status:
            query["status"] = status

        cursor = self._devices.find(query).limit(limit).sort("name", 1)
        return [mappers.document_to_netbox_device(doc) for doc in cursor]

    # -------------------------------------------------------------------------
    # VM Operations
    # -------------------------------------------------------------------------

    def get_vm(self, netbox_id: int) -> NetboxVMRecord | None:
        """Get a VM by NetBox ID."""
        doc = self._vms.find_one({"netbox_id": netbox_id})
        return mappers.document_to_netbox_vm(doc) if doc else None

    def list_vms(self, limit: int | None = None) -> list[NetboxVMRecord]:
        """List all VMs."""
        cursor = self._vms.find().sort("name", 1)
        if limit:
            cursor = cursor.limit(limit)
        return [mappers.document_to_netbox_vm(doc) for doc in cursor]

    def get_vm_count(self) -> int:
        """Get the total VM count."""
        return self._vms.count_documents({})

    def upsert_vm(self, record: NetboxVMRecord) -> None:
        """Insert or update a VM."""
        doc = mappers.netbox_vm_to_document(record)
        self._vms.replace_one(
            {"_id": doc["_id"]},
            doc,
            upsert=True,
        )

    def upsert_vms(self, records: Iterable[NetboxVMRecord]) -> int:
        """Bulk upsert VMs.

        Returns:
            The number of VMs upserted.
        """
        operations = []
        for record in records:
            doc = mappers.netbox_vm_to_document(record)
            operations.append(
                ReplaceOne(
                    {"_id": doc["_id"]},
                    doc,
                    upsert=True,
                )
            )

        if not operations:
            return 0

        result = self._vms.bulk_write(operations, ordered=False)
        return result.upserted_count + result.modified_count

    def delete_vm(self, netbox_id: int) -> bool:
        """Delete a VM."""
        result = self._vms.delete_one({"netbox_id": netbox_id})
        return result.deleted_count > 0

    def delete_vms_not_in(self, netbox_ids: set[int]) -> int:
        """Delete VMs not in the provided set of IDs.

        Returns:
            The number of VMs deleted.
        """
        if not netbox_ids:
            return 0
        result = self._vms.delete_many({"netbox_id": {"$nin": list(netbox_ids)}})
        return result.deleted_count

    def search_vms(
        self,
        name_pattern: str | None = None,
        primary_ip: str | None = None,
        cluster: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[NetboxVMRecord]:
        """Search VMs with various filters."""
        query: dict[str, Any] = {}
        if name_pattern:
            query["name"] = {"$regex": name_pattern, "$options": "i"}
        if primary_ip:
            query["primary_ip"] = primary_ip
        if cluster:
            query["cluster"] = cluster
        if status:
            query["status"] = status

        cursor = self._vms.find(query).limit(limit).sort("name", 1)
        return [mappers.document_to_netbox_vm(doc) for doc in cursor]

    # -------------------------------------------------------------------------
    # Combined Operations
    # -------------------------------------------------------------------------

    def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics for both devices and VMs."""
        return {
            "devices": {
                "count": self.get_device_count(),
            },
            "vms": {
                "count": self.get_vm_count(),
            },
        }

    def replace_all_devices(self, records: Iterable[NetboxDeviceRecord]) -> dict[str, int]:
        """Replace all devices (full cache refresh).

        Deletes existing devices and inserts new ones.

        Returns:
            Dict with 'deleted' and 'inserted' counts.
        """
        records_list = list(records)
        deleted = self._devices.delete_many({}).deleted_count

        if not records_list:
            return {"deleted": deleted, "inserted": 0}

        docs = [mappers.netbox_device_to_document(r) for r in records_list]
        result = self._devices.insert_many(docs)
        return {"deleted": deleted, "inserted": len(result.inserted_ids)}

    def replace_all_vms(self, records: Iterable[NetboxVMRecord]) -> dict[str, int]:
        """Replace all VMs (full cache refresh).

        Deletes existing VMs and inserts new ones.

        Returns:
            Dict with 'deleted' and 'inserted' counts.
        """
        records_list = list(records)
        deleted = self._vms.delete_many({}).deleted_count

        if not records_list:
            return {"deleted": deleted, "inserted": 0}

        docs = [mappers.netbox_vm_to_document(r) for r in records_list]
        result = self._vms.insert_many(docs)
        return {"deleted": deleted, "inserted": len(result.inserted_ids)}

    def get_cache_metadata(self) -> dict[str, Any] | None:
        """Get the overall cache metadata (generated_at, counts)."""
        # Use the metadata collection for storing cache-level info
        meta_coll = self._devices.database["netbox_cache_meta"]
        doc = meta_coll.find_one({"_id": "cache_metadata"})
        if doc:
            return {
                "generated_at": doc.get("generated_at"),
                "device_count": doc.get("device_count", 0),
                "vm_count": doc.get("vm_count", 0),
            }
        return None

    def set_cache_metadata(self, generated_at: datetime, device_count: int, vm_count: int) -> None:
        """Set the overall cache metadata."""
        meta_coll = self._devices.database["netbox_cache_meta"]
        meta_coll.replace_one(
            {"_id": "cache_metadata"},
            {
                "_id": "cache_metadata",
                "generated_at": generated_at,
                "device_count": device_count,
                "vm_count": vm_count,
                "updated_at": _now_utc(),
            },
            upsert=True,
        )


class MongoDBCommvaultCacheRepository:
    """MongoDB cache repository for Commvault backup job history."""

    def __init__(self, db: Database) -> None:
        self._collection: Collection = db["commvault_jobs"]

    def get_job(self, client_name: str, job_id: str) -> Mapping[str, Any] | None:
        """Get a specific job."""
        return self._collection.find_one({"client_name": client_name, "job_id": job_id})

    def list_jobs_for_client(self, client_name: str, limit: int = 50) -> list[Mapping[str, Any]]:
        """List jobs for a client, ordered by start time descending."""
        cursor = self._collection.find({"client_name": client_name}).sort("start_time", -1).limit(limit)
        return list(cursor)

    def upsert_job(self, client_name: str, job_id: str, data: Mapping[str, Any]) -> None:
        """Insert or update a job."""
        doc = dict(data)
        doc["_id"] = f"{client_name}:{job_id}"
        doc["client_name"] = client_name
        doc["job_id"] = job_id
        doc["cached_at"] = _now_utc()
        self._collection.replace_one(
            {"_id": doc["_id"]},
            doc,
            upsert=True,
        )

    def upsert_jobs(self, jobs: Iterable[tuple[str, str, Mapping[str, Any]]]) -> int:
        """Bulk upsert jobs.

        Args:
            jobs: Iterable of (client_name, job_id, data) tuples.

        Returns:
            The number of jobs upserted.
        """
        operations = []
        now = _now_utc()
        for client_name, job_id, data in jobs:
            doc = dict(data)
            doc["_id"] = f"{client_name}:{job_id}"
            doc["client_name"] = client_name
            doc["job_id"] = job_id
            doc["cached_at"] = now
            operations.append(
                ReplaceOne(
                    {"_id": doc["_id"]},
                    doc,
                    upsert=True,
                )
            )

        if not operations:
            return 0

        result = self._collection.bulk_write(operations, ordered=False)
        return result.upserted_count + result.modified_count

    def delete_jobs_for_client(self, client_name: str) -> int:
        """Delete all jobs for a client.

        Returns:
            The number of jobs deleted.
        """
        result = self._collection.delete_many({"client_name": client_name})
        return result.deleted_count

    def search_jobs(
        self,
        client_name: str | None = None,
        status: str | None = None,
        job_type: str | None = None,
        limit: int = 100,
    ) -> list[Mapping[str, Any]]:
        """Search jobs with various filters."""
        query: dict[str, Any] = {}
        if client_name:
            query["client_name"] = {"$regex": client_name, "$options": "i"}
        if status:
            query["status"] = status
        if job_type:
            query["job_type"] = job_type

        cursor = self._collection.find(query).limit(limit).sort("start_time", -1)
        return list(cursor)

    def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        pipeline = [
            {
                "$group": {
                    "_id": "$client_name",
                    "job_count": {"$sum": 1},
                    "last_job": {"$max": "$start_time"},
                }
            },
            {"$sort": {"_id": 1}},
        ]
        clients = list(self._collection.aggregate(pipeline))
        return {
            "total_jobs": self._collection.count_documents({}),
            "clients": [
                {
                    "name": c["_id"],
                    "job_count": c["job_count"],
                    "last_job": c.get("last_job"),
                }
                for c in clients
            ],
        }


__all__ = [
    "MongoDBCommvaultCacheRepository",
    "MongoDBNetBoxCacheRepository",
    "MongoDBVCenterCacheRepository",
]
