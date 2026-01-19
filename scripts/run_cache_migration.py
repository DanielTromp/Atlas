#!/usr/bin/env python3
"""Run migration 003 to migrate JSON caches to MongoDB."""

from __future__ import annotations

import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))


def main():
    from rich.console import Console
    from rich.table import Table

    console = Console()

    console.print("\n[bold]JSON Cache → MongoDB Migration[/bold]\n")

    # Check environment
    import os
    if os.getenv("ATLAS_STORAGE_BACKEND") != "mongodb":
        os.environ["ATLAS_STORAGE_BACKEND"] = "mongodb"

    # Get MongoDB client
    try:
        from infrastructure_atlas.infrastructure.mongodb import get_mongodb_client
        client = get_mongodb_client()
        app_db = client.atlas
        cache_db = client.atlas_cache
        console.print("[green]✓[/green] Connected to MongoDB")
    except Exception as e:
        console.print(f"[red]✗[/red] Failed to connect to MongoDB: {e}")
        return 1

    # Run migration 003
    console.print("\n[bold]Running migration 003: JSON caches[/bold]\n")

    import importlib
    migration = importlib.import_module(
        "infrastructure_atlas.infrastructure.mongodb.migrations.versions.003_migrate_json_caches"
    )

    try:
        results = migration.upgrade(app_db, cache_db)

        # vCenter results
        vcenter = results.get("vcenter", {})
        console.print("[bold]vCenter Cache:[/bold]")
        if vcenter.get("status") == "completed":
            console.print(f"  Configs processed: {vcenter.get('configs_processed', 0)}")
            console.print(f"  VMs migrated: {vcenter.get('vms_migrated', 0)}")
            if vcenter.get("files_processed"):
                files_table = Table(show_header=True)
                files_table.add_column("File")
                files_table.add_column("VMs", justify="right")
                for f in vcenter["files_processed"]:
                    files_table.add_row(f["file"], str(f["vm_count"]))
                console.print(files_table)
        else:
            console.print(f"  Status: {vcenter.get('status', 'unknown')}")
            console.print(f"  Reason: {vcenter.get('reason', 'N/A')}")

        console.print()

        # NetBox results
        netbox = results.get("netbox", {})
        console.print("[bold]NetBox Cache:[/bold]")
        if netbox.get("status") == "completed":
            console.print(f"  Devices migrated: {netbox.get('devices_migrated', 0)}")
            console.print(f"  VMs migrated: {netbox.get('vms_migrated', 0)}")
        else:
            console.print(f"  Status: {netbox.get('status', 'unknown')}")
            console.print(f"  Reason: {netbox.get('reason', 'N/A')}")

        console.print(f"\n[green]✓[/green] Total records migrated: {results.get('total_records', 0)}")

    except Exception as e:
        console.print(f"[red]✗[/red] Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # Verify counts
    console.print("\n[bold]Verification:[/bold]")
    verify_table = Table(show_header=True)
    verify_table.add_column("Collection")
    verify_table.add_column("Count", justify="right")

    for coll_name in ["vcenter_vms", "netbox_devices", "netbox_vms"]:
        count = cache_db[coll_name].count_documents({})
        verify_table.add_row(coll_name, str(count))

    console.print(verify_table)
    console.print("\n[bold green]Migration complete![/bold green]\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
