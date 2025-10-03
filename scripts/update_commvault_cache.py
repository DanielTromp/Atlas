#!/usr/bin/env python3
"""Refresh the cached Commvault job dataset used by the web dashboard."""

from __future__ import annotations

import argparse
from typing import Any

from fastapi import HTTPException
from rich import print

from enreach_tools.api.app import _refresh_commvault_backups_sync


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--since",
        "--since-hours",
        dest="since_hours",
        type=int,
        default=24,
        help="Only retain jobs that started within this many hours (0 = keep all cached).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximum number of jobs to request from Commvault (0 = API default).",
    )
    args = parser.parse_args()

    if args.since_hours < 0:
        parser.error("--since-hours must be zero or positive")
    if args.limit < 0:
        parser.error("--limit must be zero or positive")

    try:
        payload: dict[str, Any] = _refresh_commvault_backups_sync(limit=args.limit, since_hours=args.since_hours)
    except HTTPException as exc:
        detail = exc.detail if hasattr(exc, "detail") else str(exc)
        print(f"[red]Commvault cache update failed:[/red] {detail}")
        raise SystemExit(1) from exc

    returned = payload.get("returned")
    if returned is None:
        returned = len(payload.get("jobs") or [])
    total_cached = payload.get("total_cached")
    generated_at = payload.get("generated_at")

    summary = f"cached {returned} job(s) within last {args.since_hours}h"
    if isinstance(total_cached, int):
        summary += f"; {total_cached} total stored"
    print(f"[green]Commvault cache updated:[/green] {summary}")
    if generated_at:
        print(f"[dim]Cache timestamp: {generated_at}[/dim]")


if __name__ == "__main__":
    main()
