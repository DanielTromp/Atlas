#!/usr/bin/env python3
"""Refresh Commvault plans cache."""
import sys

# Add src to path for imports
sys.path.insert(0, str(__file__).rsplit("/", 2)[0] + "/src")

from infrastructure_atlas.interfaces.api.routes.commvault import _refresh_commvault_plans_sync

if __name__ == "__main__":
    try:
        result = _refresh_commvault_plans_sync()
        print(f"✓ Refreshed Commvault plans: {result.get('plans_count', 0)} plans")
        sys.exit(0)
    except Exception as e:
        print(f"✗ Error refreshing Commvault plans: {e}", file=sys.stderr)
        sys.exit(1)
