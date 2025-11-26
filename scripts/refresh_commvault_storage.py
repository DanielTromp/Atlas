#!/usr/bin/env python3
"""Refresh Commvault storage cache."""
import sys

# Add src to path for imports
sys.path.insert(0, str(__file__).rsplit("/", 2)[0] + "/src")

from infrastructure_atlas.interfaces.api.routes.commvault import _refresh_commvault_storage_sync

if __name__ == "__main__":
    try:
        result = _refresh_commvault_storage_sync()
        print(f"✓ Refreshed Commvault storage: {result.get('pools_count', 0)} pools")
        sys.exit(0)
    except Exception as e:
        print(f"✗ Error refreshing Commvault storage: {e}", file=sys.stderr)
        sys.exit(1)
