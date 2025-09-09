#!/usr/bin/env python3
"""Run NetBox exports (devices, vms) then merge CSVs.

This script mirrors the CLI's update flow with minimal dependencies.
Supports `--force` to re-fetch all resources.
"""

from __future__ import annotations

import os
import argparse
import subprocess
import sys

from enreach_tools.env import load_env, project_root, require_env


def main() -> int:
    parser = argparse.ArgumentParser(description="Run NetBox exports and merge")
    parser.add_argument("--force", action="store_true", help="Re-fetch all devices and VMs before merge")
    args = parser.parse_args()
    load_env()
    require_env(["NETBOX_URL", "NETBOX_TOKEN"])  # token needed for export endpoints

    steps = [
        ("devices", "netbox-export/bin/get_netbox_devices.py"),
        ("vms", "netbox-export/bin/get_netbox_vms.py"),
        ("merge", "netbox-export/bin/merge_netbox_csvs.py"),
    ]

    root = project_root()
    env = os.environ.copy()

    for name, rel in steps:
        print(f"[bold]Running {name}...[/bold]")
        script = root / rel
        cmd = [sys.executable, str(script)]
        if args.force and name in ("devices", "vms"):
            cmd.append("--force")
        code = subprocess.call(cmd, cwd=root, env=env)
        if code != 0:
            print(f"[red]Step failed:[/red] {name} (exit {code})")
            return code

    print("[green]Update complete: devices + vms + merge[/green]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
