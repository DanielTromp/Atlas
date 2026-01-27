"""Migrate JSON cache files to MongoDB.

This migration reads vCenter cache files and imports them
into MongoDB collections.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pymongo.database import Database

from infrastructure_atlas.infrastructure.logging import get_logger

logger = get_logger(__name__)

version = 3
description = "Migrate JSON cache files to MongoDB"


def _get_data_dir() -> Path:
    """Get the data directory path."""
    data_dir = os.getenv("NETBOX_DATA_DIR", "")
    if data_dir:
        return Path(data_dir)

    from infrastructure_atlas.env import project_root
    return project_root() / "data"


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


def _migrate_vcenter_cache(data_dir: Path, cache_db: Database) -> dict[str, Any]:
    """Migrate vCenter JSON cache files to MongoDB.

    Args:
        data_dir: The data directory path.
        cache_db: The cache database.

    Returns:
        Dict with migration results.
    """
    results: dict[str, Any] = {
        "configs_processed": 0,
        "vms_migrated": 0,
        "files_processed": [],
        "errors": [],
    }

    vcenter_dir = data_dir / "vcenter"
    if not vcenter_dir.exists():
        logger.info("vCenter cache directory not found: %s", vcenter_dir)
        results["status"] = "skipped"
        results["reason"] = f"Directory not found: {vcenter_dir}"
        return results

    # Find all JSON files in the vcenter directory
    json_files = list(vcenter_dir.glob("*.json"))
    if not json_files:
        logger.info("No vCenter cache files found in %s", vcenter_dir)
        results["status"] = "skipped"
        results["reason"] = "No cache files found"
        return results

    collection = cache_db["vcenter_vms"]

    for json_file in json_files:
        config_id = json_file.stem  # filename without extension
        logger.info("Processing vCenter cache file: %s (config_id: %s)", json_file.name, config_id)

        try:
            with json_file.open("r", encoding="utf-8") as fh:
                cache_data = json.load(fh)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to read vCenter cache file %s: %s", json_file.name, e)
            results["errors"].append({"file": str(json_file), "error": str(e)})
            continue

        vms_data = cache_data.get("vms", [])
        if not vms_data:
            logger.debug("No VMs found in cache file: %s", json_file.name)
            results["files_processed"].append({"file": json_file.name, "vm_count": 0})
            continue

        documents = []
        for vm_data in vms_data:
            # Create a document directly from the JSON structure
            vm_id = vm_data.get("vm_id", "")
            if not vm_id:
                continue

            doc = {
                "_id": f"{config_id}:{vm_id}",
                "config_id": config_id,
                "vm_id": vm_id,
                "name": vm_data.get("name", ""),
                "power_state": vm_data.get("power_state"),
                "cpu_count": vm_data.get("cpu_count"),
                "memory_mib": vm_data.get("memory_mib"),
                "guest_os": vm_data.get("guest_os"),
                "tools_status": vm_data.get("tools_status"),
                "hardware_version": vm_data.get("hardware_version"),
                "is_template": vm_data.get("is_template"),
                "instance_uuid": vm_data.get("instance_uuid"),
                "bios_uuid": vm_data.get("bios_uuid"),
                "ip_addresses": vm_data.get("ip_addresses", []),
                "mac_addresses": vm_data.get("mac_addresses", []),
                "host": vm_data.get("host"),
                "cluster": vm_data.get("cluster"),
                "datacenter": vm_data.get("datacenter"),
                "resource_pool": vm_data.get("resource_pool"),
                "folder": vm_data.get("folder"),
                "guest_family": vm_data.get("guest_family"),
                "guest_name": vm_data.get("guest_name"),
                "guest_full_name": vm_data.get("guest_full_name"),
                "guest_host_name": vm_data.get("guest_host_name"),
                "guest_ip_address": vm_data.get("guest_ip_address"),
                "tools_run_state": vm_data.get("tools_run_state"),
                "tools_version": vm_data.get("tools_version"),
                "tools_version_status": vm_data.get("tools_version_status"),
                "tools_install_type": vm_data.get("tools_install_type"),
                "tools_auto_update_supported": vm_data.get("tools_auto_update_supported"),
                "vcenter_url": vm_data.get("vcenter_url"),
                "network_names": vm_data.get("network_names", []),
                "custom_attributes": vm_data.get("custom_attributes", {}),
                "tags": vm_data.get("tags", []),
                "snapshots": vm_data.get("snapshots", []),
                "snapshot_count": vm_data.get("snapshot_count"),
                "disks": vm_data.get("disks", []),
                "total_disk_capacity_bytes": vm_data.get("total_disk_capacity_bytes"),
                "total_provisioned_bytes": vm_data.get("total_provisioned_bytes"),
                "updated_at": datetime.now(UTC),
            }
            documents.append(doc)

        if documents:
            # Use replace_one with upsert for idempotent migration
            from pymongo.operations import ReplaceOne
            operations = [
                ReplaceOne({"_id": doc["_id"]}, doc, upsert=True)
                for doc in documents
            ]
            result = collection.bulk_write(operations, ordered=False)
            vm_count = result.upserted_count + result.modified_count
            results["vms_migrated"] += vm_count
            results["files_processed"].append({"file": json_file.name, "vm_count": vm_count})
            logger.info("Migrated %d VMs from %s", vm_count, json_file.name)

        results["configs_processed"] += 1

    results["status"] = "completed"
    return results


def upgrade(app_db: Database, cache_db: Database) -> dict[str, Any]:
    """Run the upgrade migration.

    Args:
        app_db: The main application database (unused).
        cache_db: The cache database.

    Returns:
        Dict with migration results/stats.
    """
    results: dict[str, Any] = {
        "vcenter": {},
    }

    data_dir = _get_data_dir()
    logger.info("Migrating JSON cache files from: %s", data_dir)

    # Migrate vCenter cache
    results["vcenter"] = _migrate_vcenter_cache(data_dir, cache_db)

    # Calculate totals
    vcenter_vms = results["vcenter"].get("vms_migrated", 0)
    results["total_records"] = vcenter_vms

    return results


def downgrade(app_db: Database, cache_db: Database) -> dict[str, Any]:
    """Rollback the migration by clearing cache collections.

    Note: This does not restore the JSON files - it only clears
    the MongoDB collections that were populated by this migration.

    Args:
        app_db: The main application database (unused).
        cache_db: The cache database.

    Returns:
        Dict with rollback results.
    """
    collections = [
        "vcenter_vms",
    ]

    results: dict[str, Any] = {
        "collections_cleared": {},
    }

    for collection_name in collections:
        try:
            result = cache_db[collection_name].delete_many({})
            results["collections_cleared"][collection_name] = result.deleted_count
        except Exception as e:
            results["collections_cleared"][collection_name] = f"error: {e}"

    return results
