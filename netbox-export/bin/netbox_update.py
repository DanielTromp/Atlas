#!/usr/bin/env python3
"""Run NetBox exports (devices, vms) then merge CSVs.

This script mirrors the CLI's update flow with minimal dependencies.
Supports `--force` to re-fetch all resources.
"""

from __future__ import annotations

import argparse

from enreach_tools.application.services.netbox import NetboxExportService
from enreach_tools.env import load_env, require_env


def main() -> int:
    parser = argparse.ArgumentParser(description="Run NetBox exports and merge")
    parser.add_argument("--force", action="store_true", help="Re-fetch all devices and VMs before merge")
    parser.add_argument("--verbose", action="store_true", help="Log verbose exporter progress")
    parser.add_argument(
        "--no-refresh-cache",
        dest="refresh_cache",
        action="store_false",
        help="Reuse the existing NetBox cache snapshot without contacting the API",
    )
    parser.set_defaults(refresh_cache=True)
    args = parser.parse_args()
    load_env()
    require_env(["NETBOX_URL", "NETBOX_TOKEN"])  # token needed for export endpoints

    print("[bold]Running NetBox export service...[/bold]")
    service = NetboxExportService.from_env()
    try:
        service.export_all(force=args.force, verbose=args.verbose, refresh_cache=args.refresh_cache)
    except Exception as exc:
        print(f"[red]NetBox export failed:[/red] {exc}")
        return 1

    print("[green]Update complete: devices + vms + merge[/green]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
