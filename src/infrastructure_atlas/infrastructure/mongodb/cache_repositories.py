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
    "MongoDBVCenterCacheRepository",
]
