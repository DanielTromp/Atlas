#!/usr/bin/env python3
"""Publish the CMDB Excel to Confluence as an attachment."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

from rich import print

from enreach_tools.env import load_env, project_root


def main() -> int:
    load_env()

    parser = argparse.ArgumentParser(description="Publish standard CMDB Excel to Confluence")
    parser.add_argument("--page-id", default=os.getenv("CONFLUENCE_CMDB_PAGE_ID") or os.getenv("CONFLUENCE_PAGE_ID"), help="Confluence page ID")
    parser.add_argument("--name", default="Systems CMDB.xlsx", help="Attachment name")
    parser.add_argument("--comment", default="", help="Version comment")
    args = parser.parse_args()

    root = project_root()
    upload_script = root / "netbox-export/bin/confluence_upload_attachment.py"

    file_path = "data/Systems CMDB.xlsx"

    cmd = [
        sys.executable,
        str(upload_script),
        "--file",
        file_path,
    ]

    if args.page_id:
        cmd.extend(["--page-id", args.page_id])
    if args.name:
        cmd.extend(["--name", args.name])
    if args.comment:
        cmd.extend(["--comment", args.comment])

    print("[bold]Publishing CMDB to Confluence...[/bold]")
    return subprocess.call(cmd, cwd=root, env=os.environ.copy())


if __name__ == "__main__":
    raise SystemExit(main())
