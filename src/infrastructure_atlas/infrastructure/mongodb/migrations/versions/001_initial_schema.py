"""Initial MongoDB schema setup with indexes.

This migration creates all necessary collections and indexes for the
Infrastructure Atlas MongoDB backend.
"""

from __future__ import annotations

from typing import Any

from pymongo.database import Database

from infrastructure_atlas.infrastructure.mongodb.indexes import (
    create_application_indexes,
    create_cache_indexes,
)

version = 1
description = "Initial schema setup with indexes"


def upgrade(app_db: Database, cache_db: Database) -> dict[str, Any]:
    """Create all collections and indexes.

    Args:
        app_db: The main application database.
        cache_db: The cache database.

    Returns:
        Dict with migration results.
    """
    results: dict[str, Any] = {
        "app_indexes": {},
        "cache_indexes": {},
    }

    # Create application indexes
    app_index_results = create_application_indexes(app_db)
    results["app_indexes"] = app_index_results

    # Create cache indexes
    cache_index_results = create_cache_indexes(cache_db)
    results["cache_indexes"] = cache_index_results

    # Count total indexes created
    total_app = sum(len(indexes) for indexes in app_index_results.values())
    total_cache = sum(len(indexes) for indexes in cache_index_results.values())
    results["total_indexes_created"] = total_app + total_cache
    results["app_collections"] = len(app_index_results)
    results["cache_collections"] = len(cache_index_results)

    return results


def downgrade(app_db: Database, cache_db: Database) -> dict[str, Any]:
    """Drop all collections (use with caution!).

    This is a destructive operation that drops all application and cache
    collections. Use only in development or when you're sure you want to
    start fresh.

    Args:
        app_db: The main application database.
        cache_db: The cache database.

    Returns:
        Dict with rollback results.
    """
    results: dict[str, Any] = {
        "dropped_app_collections": [],
        "dropped_cache_collections": [],
    }

    # Get list of collections (excluding system collections)
    app_collections = [
        name for name in app_db.list_collection_names()
        if not name.startswith("system.") and name != "_migrations"
    ]
    cache_collections = [
        name for name in cache_db.list_collection_names()
        if not name.startswith("system.")
    ]

    # Drop application collections
    for collection_name in app_collections:
        app_db.drop_collection(collection_name)
        results["dropped_app_collections"].append(collection_name)

    # Drop cache collections
    for collection_name in cache_collections:
        cache_db.drop_collection(collection_name)
        results["dropped_cache_collections"].append(collection_name)

    return results
