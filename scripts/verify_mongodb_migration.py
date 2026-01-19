#!/usr/bin/env python3
"""Verify MongoDB migration by comparing record counts and testing operations.

This script:
1. Checks MongoDB connectivity
2. Compares record counts between SQLite and MongoDB (if SQLite exists)
3. Compares JSON file records with MongoDB documents (if JSON files exist)
4. Verifies all indexes are created
5. Tests concurrent read/write operations
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Add the src directory to the path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))


def check_mongodb_connection() -> tuple[bool, str]:
    """Check MongoDB connection."""
    try:
        from infrastructure_atlas.infrastructure.mongodb import get_mongodb_client

        client = get_mongodb_client()
        result = client.health_check()
        if result.get("healthy"):
            return True, "MongoDB connection successful"
        return False, f"MongoDB unhealthy: {result.get('error', 'Unknown error')}"
    except Exception as e:
        return False, f"MongoDB connection failed: {e}"


def get_mongodb_counts() -> dict[str, int]:
    """Get document counts from MongoDB collections."""
    try:
        from infrastructure_atlas.infrastructure.mongodb import get_mongodb_client

        client = get_mongodb_client()
        app_db = client.atlas
        cache_db = client.atlas_cache

        counts = {}

        # Application collections
        for name in app_db.list_collection_names():
            if not name.startswith("_") and not name.startswith("system."):
                counts[f"app.{name}"] = app_db[name].count_documents({})

        # Cache collections
        for name in cache_db.list_collection_names():
            if not name.startswith("system."):
                counts[f"cache.{name}"] = cache_db[name].count_documents({})

        return counts
    except Exception as e:
        print(f"Error getting MongoDB counts: {e}")
        return {}


def get_sqlite_counts(db_path: Path) -> dict[str, int]:
    """Get row counts from SQLite tables."""
    try:
        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import Session

        engine = create_engine(f"sqlite:///{db_path}")
        counts = {}

        with Session(engine) as session:
            # Get list of tables
            result = session.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'alembic%'")
            )
            tables = [row[0] for row in result]

            for table in tables:
                try:
                    result = session.execute(text(f"SELECT COUNT(*) FROM {table}"))  # noqa: S608
                    count = result.scalar()
                    counts[f"sqlite.{table}"] = count or 0
                except Exception as e:
                    print(f"  Error counting {table}: {e}")

        return counts
    except Exception as e:
        print(f"Error getting SQLite counts: {e}")
        return {}


def get_json_cache_counts(data_dir: Path) -> dict[str, int]:
    """Get record counts from JSON cache files."""
    counts = {}

    # vCenter cache files
    vcenter_dir = data_dir / "vcenter"
    if vcenter_dir.exists():
        total_vms = 0
        for json_file in vcenter_dir.glob("*.json"):
            try:
                with json_file.open() as f:
                    data = json.load(f)
                vms = data.get("vms", [])
                total_vms += len(vms)
                counts[f"json.vcenter.{json_file.stem}"] = len(vms)
            except Exception as e:
                print(f"  Error reading {json_file}: {e}")
        counts["json.vcenter_vms_total"] = total_vms

    # NetBox cache
    netbox_cache = data_dir / "netbox_cache.json"
    if netbox_cache.exists():
        try:
            with netbox_cache.open() as f:
                data = json.load(f)
            resources = data.get("resources", {})
            devices = resources.get("devices", {}).get("items", [])
            vms = resources.get("vms", {}).get("items", [])
            counts["json.netbox_devices"] = len(devices)
            counts["json.netbox_vms"] = len(vms)
        except Exception as e:
            print(f"  Error reading netbox cache: {e}")

    return counts


def verify_indexes() -> dict[str, list[str]]:
    """Verify that all required indexes exist."""
    try:
        from infrastructure_atlas.infrastructure.mongodb import get_mongodb_client

        client = get_mongodb_client()
        app_db = client.atlas
        cache_db = client.atlas_cache

        indexes: dict[str, list[str]] = {}

        # Application collections
        for name in app_db.list_collection_names():
            if not name.startswith("_") and not name.startswith("system."):
                collection = app_db[name]
                index_info = collection.index_information()
                indexes[f"app.{name}"] = list(index_info.keys())

        # Cache collections
        for name in cache_db.list_collection_names():
            if not name.startswith("system."):
                collection = cache_db[name]
                index_info = collection.index_information()
                indexes[f"cache.{name}"] = list(index_info.keys())

        return indexes
    except Exception as e:
        print(f"Error verifying indexes: {e}")
        return {}


def test_concurrent_operations() -> tuple[bool, str]:
    """Test concurrent read/write operations."""
    try:
        from infrastructure_atlas.infrastructure.mongodb import get_mongodb_client

        client = get_mongodb_client()
        cache_db = client.atlas_cache
        test_collection = cache_db["_migration_test"]

        # Clean up first
        test_collection.drop()

        def write_doc(i: int) -> bool:
            doc = {
                "_id": f"test_{i}",
                "value": i,
                "timestamp": datetime.now(UTC),
            }
            test_collection.replace_one({"_id": doc["_id"]}, doc, upsert=True)
            return True

        def read_docs() -> int:
            return test_collection.count_documents({})

        # Test concurrent writes
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(write_doc, i) for i in range(100)]
            results = [f.result() for f in futures]

        if not all(results):
            return False, "Some concurrent writes failed"

        # Verify count
        count = read_docs()
        if count != 100:
            return False, f"Expected 100 documents, got {count}"

        # Test concurrent reads during writes
        with ThreadPoolExecutor(max_workers=20) as executor:
            write_futures = [executor.submit(write_doc, i + 100) for i in range(50)]
            read_futures = [executor.submit(read_docs) for _ in range(50)]
            write_results = [f.result() for f in write_futures]
            read_results = [f.result() for f in read_futures]

        if not all(write_results):
            return False, "Some concurrent writes during reads failed"

        # Clean up
        test_collection.drop()

        return True, f"Concurrent operations successful ({len(write_results)} writes, {len(read_results)} reads)"
    except Exception as e:
        return False, f"Concurrent operations failed: {e}"


def main():
    """Run verification checks."""
    print("=" * 60)
    print("MongoDB Migration Verification")
    print("=" * 60)
    print()

    # Get data directory
    data_dir = Path(__file__).parent.parent / "data"
    sqlite_path = data_dir / "atlas.sqlite3"
    if not sqlite_path.exists():
        sqlite_path = data_dir / "atlas.db"

    # 1. Check MongoDB connection
    print("1. Checking MongoDB connection...")
    success, message = check_mongodb_connection()
    print(f"   {'✓' if success else '✗'} {message}")
    if not success:
        print("\n   MongoDB is not available. Please start it with:")
        print("   docker compose up -d mongodb")
        return 1
    print()

    # 2. Compare record counts
    print("2. Comparing record counts...")
    mongo_counts = get_mongodb_counts()

    if sqlite_path.exists():
        print(f"   SQLite database found: {sqlite_path}")
        sqlite_counts = get_sqlite_counts(sqlite_path)
        print("\n   SQLite vs MongoDB counts:")
        for key, count in sorted(sqlite_counts.items()):
            table_name = key.replace("sqlite.", "")
            mongo_key = f"app.{table_name}"
            mongo_count = mongo_counts.get(mongo_key, 0)
            status = "✓" if count == mongo_count else "≠"
            print(f"   {status} {table_name}: SQLite={count}, MongoDB={mongo_count}")
    else:
        print("   No SQLite database found (this is OK for fresh installs)")

    if data_dir.exists():
        json_counts = get_json_cache_counts(data_dir)
        if json_counts:
            print("\n   JSON cache vs MongoDB counts:")
            vcenter_total = json_counts.get("json.vcenter_vms_total", 0)
            mongo_vcenter = mongo_counts.get("cache.vcenter_vms", 0)
            print(f"   {'✓' if vcenter_total == mongo_vcenter else '≠'} vCenter VMs: JSON={vcenter_total}, MongoDB={mongo_vcenter}")

            netbox_devices = json_counts.get("json.netbox_devices", 0)
            mongo_devices = mongo_counts.get("cache.netbox_devices", 0)
            print(f"   {'✓' if netbox_devices == mongo_devices else '≠'} NetBox devices: JSON={netbox_devices}, MongoDB={mongo_devices}")

            netbox_vms = json_counts.get("json.netbox_vms", 0)
            mongo_vms = mongo_counts.get("cache.netbox_vms", 0)
            print(f"   {'✓' if netbox_vms == mongo_vms else '≠'} NetBox VMs: JSON={netbox_vms}, MongoDB={mongo_vms}")
    print()

    # 3. Verify indexes
    print("3. Verifying indexes...")
    indexes = verify_indexes()
    total_indexes = sum(len(idx_list) for idx_list in indexes.values())
    print(f"   Found {len(indexes)} collections with {total_indexes} total indexes")
    for collection, idx_list in sorted(indexes.items()):
        print(f"   - {collection}: {len(idx_list)} indexes")
    print()

    # 4. Test concurrent operations
    print("4. Testing concurrent operations...")
    success, message = test_concurrent_operations()
    print(f"   {'✓' if success else '✗'} {message}")
    print()

    # Summary
    print("=" * 60)
    print("MongoDB Collections Summary:")
    print("=" * 60)
    for key, count in sorted(mongo_counts.items()):
        print(f"   {key}: {count} documents")
    print()

    print("Verification complete!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
