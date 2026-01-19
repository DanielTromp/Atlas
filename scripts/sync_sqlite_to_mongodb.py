#!/usr/bin/env python3
"""Sync remaining SQLite data to MongoDB.

This script clears target MongoDB collections and re-migrates all data
from SQLite to ensure MongoDB has complete data.
"""

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

    console.print("\n[bold]SQLite → MongoDB Data Sync[/bold]\n")

    # Check environment
    import os
    if os.getenv("ATLAS_STORAGE_BACKEND") != "mongodb":
        console.print("[yellow]Warning: ATLAS_STORAGE_BACKEND is not set to 'mongodb'[/yellow]")
        console.print("Setting it for this script...\n")
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

    # Check SQLite exists
    from infrastructure_atlas.env import project_root
    sqlite_paths = [
        project_root() / "data" / "atlas.sqlite3",
        project_root() / "data" / "atlas.db",
    ]
    sqlite_path = None
    for p in sqlite_paths:
        if p.exists():
            sqlite_path = p
            break

    if not sqlite_path:
        console.print("[red]✗[/red] SQLite database not found")
        return 1

    console.print(f"[green]✓[/green] Found SQLite: {sqlite_path}\n")

    # Collections to clear and re-migrate
    collections = [
        "users",
        "user_api_keys",
        "global_api_keys",
        "secure_settings",
        "role_permissions",
        "chat_sessions",
        "chat_messages",
        "vcenter_configs",
        "foreman_configs",
        "module_configs",
        "playground_sessions",
        "playground_usage",
        "playground_presets",
        "puppet_configs",
        "ai_activity_logs",
        "bot_platform_accounts",
        "bot_conversations",
        "bot_messages",
        "bot_webhook_configs",
    ]

    # Step 1: Clear existing data
    console.print("[bold]Step 1: Clearing MongoDB collections[/bold]")
    cleared_table = Table(show_header=True)
    cleared_table.add_column("Collection")
    cleared_table.add_column("Deleted", justify="right")

    for coll_name in collections:
        try:
            result = app_db[coll_name].delete_many({})
            cleared_table.add_row(coll_name, str(result.deleted_count))
        except Exception as e:
            cleared_table.add_row(coll_name, f"[red]Error: {e}[/red]")

    console.print(cleared_table)
    console.print()

    # Step 2: Run migration
    console.print("[bold]Step 2: Migrating data from SQLite[/bold]")

    import importlib
    migration = importlib.import_module(
        "infrastructure_atlas.infrastructure.mongodb.migrations.versions.002_migrate_sqlite_data"
    )

    try:
        results = migration.upgrade(app_db, cache_db)

        migrated_table = Table(show_header=True)
        migrated_table.add_column("Table")
        migrated_table.add_column("Records", justify="right")

        for table, count in results.get("tables_migrated", {}).items():
            migrated_table.add_row(table, str(count))

        console.print(migrated_table)
        console.print(f"\n[green]✓[/green] Total records migrated: {results.get('total_records', 0)}")

        if results.get("skipped_tables"):
            console.print(f"[yellow]Skipped tables (not in SQLite):[/yellow] {', '.join(results['skipped_tables'])}")

    except Exception as e:
        console.print(f"[red]✗[/red] Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # Step 3: Verify counts
    console.print("\n[bold]Step 3: Verification[/bold]")

    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    engine = create_engine(f"sqlite:///{sqlite_path}")

    verify_table = Table(show_header=True)
    verify_table.add_column("Collection")
    verify_table.add_column("SQLite", justify="right")
    verify_table.add_column("MongoDB", justify="right")
    verify_table.add_column("Status")

    with Session(engine) as session:
        for coll_name in collections:
            try:
                # Get SQLite count
                result = session.execute(text(f"SELECT COUNT(*) FROM {coll_name}"))
                sqlite_count = result.scalar() or 0
            except Exception:
                sqlite_count = "N/A"

            # Get MongoDB count
            try:
                mongo_count = app_db[coll_name].count_documents({})
            except Exception:
                mongo_count = "N/A"

            if sqlite_count == mongo_count:
                status = "[green]✓ Match[/green]"
            elif sqlite_count == "N/A":
                status = "[yellow]Table not in SQLite[/yellow]"
            else:
                status = f"[red]✗ Mismatch[/red]"

            verify_table.add_row(coll_name, str(sqlite_count), str(mongo_count), status)

    console.print(verify_table)
    console.print("\n[bold green]Migration complete![/bold green]\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
