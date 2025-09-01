#!/usr/bin/env python3
import argparse
import os
import subprocess
import sys

from rich import print

from enreach_tools.env import load_env, project_root


def main() -> int:
    load_env()

    parser = argparse.ArgumentParser(description="Publish standard CMDB Excel to SharePoint")
    parser.add_argument("--auth", default="userpass", choices=["userpass", "app"], help="Auth mode")
    parser.add_argument("--replace", dest="replace", action="store_true", default=True, help="Replace if exists")
    parser.add_argument("--no-replace", dest="replace", action="store_false", help="Do not replace")
    args = parser.parse_args()

    root = project_root()
    upload_script = root / "netbox-export/bin/sharepoint_upload.py"

    file_path = "netbox-export/data/Systems CMDB.xlsx"
    dest_path = "Important Info/Autosync/Systems CMDB.xlsx"

    cmd = [
        sys.executable,
        str(upload_script),
        "--file",
        file_path,
        "--dest",
        dest_path,
        "--auth",
        args.auth,
    ]
    cmd.append("--replace" if args.replace else "--no-replace")

    print("[bold]Publishing CMDB to SharePoint...[/bold]")
    return subprocess.call(cmd, cwd=root, env=os.environ.copy())


if __name__ == "__main__":
    raise SystemExit(main())

