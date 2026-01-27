"""Drop NetBox cache collections.

The NetBox export/caching functionality has been removed from Atlas.
This migration drops the obsolete collections that were used for caching
NetBox devices and VMs.

Collections dropped:
- netbox_devices
- netbox_vms
- netbox_cache_meta
"""

from __future__ import annotations

from typing import Any

from pymongo.database import Database

from infrastructure_atlas.infrastructure.logging import get_logger

logger = get_logger(__name__)

version = 4
description = "Drop NetBox cache collections"

# Collections to drop
NETBOX_COLLECTIONS = [
    "netbox_devices",
    "netbox_vms",
    "netbox_cache_meta",
]


def upgrade(app_db: Database, cache_db: Database) -> dict[str, Any]:
    """Drop NetBox cache collections.

    Args:
        app_db: The main application database (unused).
        cache_db: The cache database.

    Returns:
        Dict with migration results.
    """
    results: dict[str, Any] = {
        "collections_dropped": [],
        "collections_not_found": [],
        "errors": [],
    }

    existing_collections = cache_db.list_collection_names()

    for collection_name in NETBOX_COLLECTIONS:
        if collection_name in existing_collections:
            try:
                cache_db.drop_collection(collection_name)
                results["collections_dropped"].append(collection_name)
                logger.info("Dropped collection: %s", collection_name)
            except Exception as e:
                results["errors"].append({"collection": collection_name, "error": str(e)})
                logger.error("Failed to drop collection %s: %s", collection_name, e)
        else:
            results["collections_not_found"].append(collection_name)
            logger.debug("Collection not found (already removed): %s", collection_name)

    return results


def downgrade(app_db: Database, cache_db: Database) -> dict[str, Any]:
    """Recreate NetBox cache collections (empty).

    Note: This does not restore any data, just recreates the empty collections
    with their indexes.

    Args:
        app_db: The main application database (unused).
        cache_db: The cache database.

    Returns:
        Dict with rollback results.
    """
    from pymongo import ASCENDING, IndexModel

    results: dict[str, Any] = {
        "collections_created": [],
        "errors": [],
    }

    # Recreate collections with indexes
    netbox_devices_indexes = [
        IndexModel([("netbox_id", ASCENDING)], unique=True, name="idx_netbox_id_unique"),
        IndexModel([("name", ASCENDING)], name="idx_name"),
        IndexModel([("primary_ip", ASCENDING)], sparse=True, name="idx_primary_ip"),
        IndexModel([("site", ASCENDING)], name="idx_site"),
        IndexModel([("status", ASCENDING)], name="idx_status"),
    ]

    netbox_vms_indexes = [
        IndexModel([("netbox_id", ASCENDING)], unique=True, name="idx_netbox_id_unique"),
        IndexModel([("name", ASCENDING)], name="idx_name"),
        IndexModel([("primary_ip", ASCENDING)], sparse=True, name="idx_primary_ip"),
        IndexModel([("cluster", ASCENDING)], sparse=True, name="idx_cluster"),
        IndexModel([("status", ASCENDING)], name="idx_status"),
    ]

    collections_to_create = [
        ("netbox_devices", netbox_devices_indexes),
        ("netbox_vms", netbox_vms_indexes),
        ("netbox_cache_meta", []),
    ]

    for collection_name, indexes in collections_to_create:
        try:
            collection = cache_db[collection_name]
            if indexes:
                collection.create_indexes(indexes)
            results["collections_created"].append(collection_name)
            logger.info("Created collection: %s", collection_name)
        except Exception as e:
            results["errors"].append({"collection": collection_name, "error": str(e)})
            logger.error("Failed to create collection %s: %s", collection_name, e)

    return results
