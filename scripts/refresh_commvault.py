#!/usr/bin/env python3
"""Refresh all Commvault caches (backups, plans, storage)."""
import sys

# Add src to path for imports
sys.path.insert(0, str(__file__).rsplit("/", 2)[0] + "/src")

from infrastructure_atlas.interfaces.api.routes.commvault import (
    _refresh_commvault_backups_sync,
    _refresh_commvault_plans_sync,
    _refresh_commvault_storage_sync,
)

if __name__ == "__main__":
    errors = []

    # Refresh backups (with merge logic)
    try:
        result = _refresh_commvault_backups_sync(limit=0, since_hours=24)
        print(f"✓ Backups: {result.get('new_jobs', 0)} new, {result.get('updated_jobs', 0)} updated, {result.get('total_cached', 0)} total")
    except Exception as e:
        error_msg = f"Backups refresh failed: {e}"
        print(f"✗ {error_msg}", file=sys.stderr)
        errors.append(error_msg)

    # Refresh plans
    try:
        result = _refresh_commvault_plans_sync()
        print(f"✓ Plans: {result.get('plans_count', 0)} plans refreshed")
    except Exception as e:
        error_msg = f"Plans refresh failed: {e}"
        print(f"✗ {error_msg}", file=sys.stderr)
        errors.append(error_msg)

    # Refresh storage
    try:
        result = _refresh_commvault_storage_sync()
        print(f"✓ Storage: {result.get('pools_count', 0)} pools refreshed")
    except Exception as e:
        error_msg = f"Storage refresh failed: {e}"
        print(f"✗ {error_msg}", file=sys.stderr)
        errors.append(error_msg)

    if errors:
        print(f"\n✗ Completed with {len(errors)} error(s)", file=sys.stderr)
        sys.exit(1)
    else:
        print("\n✓ All Commvault caches refreshed successfully")
        sys.exit(0)
