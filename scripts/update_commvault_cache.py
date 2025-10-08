#!/usr/bin/env python3
"""Refresh the cached Commvault job and storage datasets used by the web dashboard."""

from __future__ import annotations

import argparse
import os
import warnings
from typing import Any

from fastapi import HTTPException
from rich import print

from enreach_tools.api.app import _refresh_commvault_backups_sync, _refresh_commvault_storage_sync

try:  # optional dependency; only present when TLS warnings emitted
    from urllib3 import disable_warnings
    from urllib3.exceptions import InsecureRequestWarning
except Exception:  # pragma: no cover - urllib3 not installed
    disable_warnings = None  # type: ignore[assignment]
    InsecureRequestWarning = None  # type: ignore[assignment]


def _maybe_disable_tls_warnings() -> None:
    """Mute urllib3 TLS warnings when TLS verification is intentionally disabled."""

    verify = os.getenv("COMMVAULT_VERIFY_TLS")
    if verify is None:
        return
    if verify.strip().lower() in {"0", "false", "no", "off"}:
        if disable_warnings and InsecureRequestWarning:
            disable_warnings(InsecureRequestWarning)
        else:
            warnings.filterwarnings("ignore", category=Warning, module="urllib3")


def main() -> None:
    _maybe_disable_tls_warnings()

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
    parser.add_argument(
        "--skip-storage",
        action="store_true",
        help="Skip refreshing Commvault storage pool cache.",
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
        print('[yellow]Hint: check network connectivity to the CommServe host or adjust COMMVAULT_TIMEOUT.[/yellow]')
        raise SystemExit(1) from exc

    returned = payload.get("returned")
    if returned is None:
        returned = len(payload.get("jobs") or [])
    total_cached = payload.get("total_cached")
    generated_at = payload.get("generated_at")
    new_jobs = payload.get("new_jobs")
    updated_jobs = payload.get("updated_jobs")

    summary = f"cached {returned} job(s) within last {args.since_hours}h"
    if isinstance(total_cached, int):
        summary += f"; {total_cached} total stored"
    if isinstance(new_jobs, int) or isinstance(updated_jobs, int):
        summary += f"; {new_jobs or 0} new / {updated_jobs or 0} updated"
    print(f"[green]Commvault cache updated:[/green] {summary}")
    if generated_at:
        print(f"[dim]Cache timestamp: {generated_at}[/dim]")

    if args.skip_storage:
        return

    try:
        storage_payload: dict[str, Any] = _refresh_commvault_storage_sync()
    except HTTPException as exc:
        detail = exc.detail if hasattr(exc, "detail") else str(exc)
        print(f"[yellow]Storage cache refresh failed:[/yellow] {detail}")
        print('[dim]Storage cache was not refreshed; existing cache (if any) remains untouched.[/dim]')
        return

    pools = storage_payload.get("pools") or []
    total_cached_pools = storage_payload.get("total_cached", len(pools))
    storage_generated_at = storage_payload.get("generated_at")

    total_capacity = sum(p.get("total_capacity_bytes") or 0 for p in pools)
    used_capacity = sum(p.get("used_bytes") or 0 for p in pools)

    print(
        f"[green]Commvault storage cache updated:[/green] {total_cached_pools} pool(s)"
        f" — total capacity {format_bytes(total_capacity)}, used {format_bytes(used_capacity)}"
    )
    if storage_generated_at:
        print(f"[dim]Storage cache timestamp: {storage_generated_at}[/dim]")


def format_bytes(value: int | None) -> str:
    if not value:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    size = float(value)
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024
        idx += 1
    precision = 0 if size >= 100 else 1 if size >= 10 else 2
    return f"{size:.{precision}f} {units[idx]}"


if __name__ == "__main__":
    main()
