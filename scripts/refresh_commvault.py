#!/usr/bin/env python3
"""Refresh all Commvault caches (backups, plans, storage)."""
import sys
from datetime import datetime, UTC

# Add src to path for imports
sys.path.insert(0, str(__file__).rsplit("/", 2)[0] + "/src")

from infrastructure_atlas.interfaces.api.routes.commvault import (
    _load_commvault_backups,
    _refresh_commvault_backups_sync,
    _refresh_commvault_plans_sync,
    _refresh_commvault_storage_sync,
)

if __name__ == "__main__":
    errors = []

    # Calculate since_hours based on cache age
    # Default to 30 days, but extend if cache is older
    since_hours = 30 * 24  # 30 days default
    try:
        cache = _load_commvault_backups()
        generated_at_str = cache.get("generated_at")
        if generated_at_str:
            generated_at = datetime.fromisoformat(generated_at_str.replace("Z", "+00:00"))
            age_hours = int((datetime.now(UTC) - generated_at).total_seconds() / 3600)
            # Add 24 hours buffer to ensure we overlap with existing cache
            since_hours = max(since_hours, age_hours + 24)
            print(f"Cache is {age_hours} hours old, fetching last {since_hours} hours")
    except Exception:
        pass

    # Refresh backups (with merge logic)
    try:
        result = _refresh_commvault_backups_sync(limit=0, since_hours=since_hours)
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
