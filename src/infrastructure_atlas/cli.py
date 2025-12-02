from __future__ import annotations

import asyncio
import inspect
import json
import os
import shlex
import subprocess
import sys
from collections.abc import Iterable, Sequence
from contextlib import ExitStack
from dataclasses import asdict
from datetime import UTC, datetime
from getpass import getuser
from time import monotonic
from typing import Annotated
from zoneinfo import ZoneInfo

import typer
from fastapi import HTTPException
from rich import print
from rich.console import Console
from rich.table import Table

from .api.app import (
    _build_dataset_command,
    _build_dataset_metadata,
    _collect_task_dataset_definitions,
)
from .application.context import ServiceContext
from .application.dto.admin import admin_user_to_dto, admin_users_to_dto
from .application.orchestration import AsyncJobRunner
from .application.services import NetboxExportService, create_admin_service
from .db import get_sessionmaker
from .db.setup import init_database
from .domain.tasks import JobStatus
from .env import load_env, project_root, require_env
from .infrastructure.caching import get_cache_registry
from .infrastructure.logging import get_logger, logging_context
from .infrastructure.metrics import record_netbox_export
from .infrastructure.queues import InMemoryJobQueue
from .infrastructure.tracing import init_tracing, span, tracing_enabled
from .interfaces.cli.commvault import app as commvault_cli_app
from .interfaces.cli.vcenter import app as vcenter_cli_app

# Enable -h as an alias for --help everywhere
HELP_CTX = {"help_option_names": ["-h", "--help"]}

app = typer.Typer(help="Infrastructure Atlas CLI", context_settings=HELP_CTX)

console = Console()
logger = get_logger(__name__)

try:
    AMS_TZ = ZoneInfo("Europe/Amsterdam")
except Exception:
    AMS_TZ = UTC


def _run_script(relpath: str, *args: str) -> int:
    """Run a Python script at repo-relative path with inherited env."""
    root = project_root()
    script = root / relpath
    if not script.exists():
        print(f"[red]Script not found:[/red] {script}")
        return 1
    cmd = [sys.executable, str(script), *args]
    args_display = " ".join(args)
    with logging_context(script=relpath, script_args=args_display or None):
        logger.info(
            "Invoking legacy script %s",
            relpath,
            extra={
                "event": "legacy_script_start",
            },
        )
        rc = subprocess.call(cmd, cwd=root, env=os.environ.copy())
        logger.info(
            "Legacy script finished %s (rc=%s)",
            relpath,
            rc,
            extra={
                "event": "legacy_script_complete",
                "return_code": rc,
            },
        )
    return rc


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _resolve_actor() -> str:
    candidates = [
        os.getenv("ATLAS_LOG_ACTOR"),
        os.getenv("LOGNAME"),
        os.getenv("USER"),
        os.getenv("USERNAME"),
    ]
    for candidate in candidates:
        if candidate:
            return candidate
    try:
        return getuser()
    except Exception:
        return "unknown"


@app.callback()
def _common(
    ctx: typer.Context,
    override_env: bool = typer.Option(False, "--override-env", help="Override existing env vars from .env"),
):
    env_path = load_env(override=override_env)
    print(f"[dim]Using .env: {env_path}[/dim]")
    command = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "<root>"
    actor = _resolve_actor()
    stack = ExitStack()
    stack.enter_context(
        logging_context(
            actor=actor,
            raw_command=command,
            command_path=ctx.command_path or "<root>",
            cwd=os.getcwd(),
        )
    )
    ctx.call_on_close(stack.close)
    logger.info(
        "CLI command invoked: %s",
        command,
        extra={
            "event": "cli_invocation",
            "invoked_command": ctx.command_path or "atlas",
        },
    )


# Import extracted CLI modules
from .interfaces.cli import database as database_cli
from .interfaces.cli import export as export_cli
from .interfaces.cli import foreman as foreman_cli
from .interfaces.cli import jira as jira_cli
from .interfaces.cli import confluence as confluence_cli
from .interfaces.cli import netbox as netbox_cli
from .interfaces.cli import search as search_cli
from .interfaces.cli import server as server_cli
from .interfaces.cli import tasks as tasks_cli
from .interfaces.cli import users as users_cli_module
from .interfaces.cli import zabbix as zabbix_cli


def _register_cli_commands() -> None:
    """Register CLI commands conditionally based on module registry."""
    from .infrastructure.modules import get_module_registry, initialize_modules

    # Initialize module system
    initialize_modules()
    registry = get_module_registry()

    # Core commands (always enabled)
    app.add_typer(server_cli.app, name="api")
    app.add_typer(tasks_cli.app, name="tasks")
    app.add_typer(search_cli.app, name="search")
    app.add_typer(database_cli.app, name="db")
    app.add_typer(users_cli_module.app, name="users")

    # Module-specific commands (conditional)
    if registry.is_enabled("netbox"):
        app.add_typer(netbox_cli.app, name="netbox")
        app.add_typer(export_cli.app, name="export")
        logger.debug("Enabled NetBox CLI commands")
    else:
        logger.debug("NetBox module disabled, skipping CLI commands")

    if registry.is_enabled("vcenter"):
        app.add_typer(vcenter_cli_app, name="vcenter")
        logger.debug("Enabled vCenter CLI commands")
    else:
        logger.debug("vCenter module disabled, skipping CLI commands")

    if registry.is_enabled("commvault"):
        app.add_typer(commvault_cli_app, name="commvault")
        logger.debug("Enabled Commvault CLI commands")
    else:
        logger.debug("Commvault module disabled, skipping CLI commands")

    if registry.is_enabled("zabbix"):
        app.add_typer(zabbix_cli.app, name="zabbix")
        logger.debug("Enabled Zabbix CLI commands")
    else:
        logger.debug("Zabbix module disabled, skipping CLI commands")

    if registry.is_enabled("jira"):
        app.add_typer(jira_cli.app, name="jira")
        logger.debug("Enabled Jira CLI commands")
    else:
        logger.debug("Jira module disabled, skipping CLI commands")

    if registry.is_enabled("confluence"):
        app.add_typer(confluence_cli.app, name="confluence")
        logger.debug("Enabled Confluence CLI commands")
    else:
        logger.debug("Confluence module disabled, skipping CLI commands")

    if registry.is_enabled("foreman"):
        app.add_typer(foreman_cli.app, name="foreman")
        logger.debug("Enabled Foreman CLI commands")
    else:
        logger.debug("Foreman module is disabled, skipping CLI commands")


# Register commands on module initialization
_register_cli_commands()


def _safe_int(value: object, default: int = 0) -> int:
    try:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int | float):
            return int(value)
        if isinstance(value, str):
            cleaned = value.strip()
            if not cleaned:
                return default
            return int(float(cleaned)) if any(ch in cleaned for ch in (".", "e", "E")) else int(cleaned)
    except Exception:
        return default
    return default


@app.command("cache-stats")
def cache_stats(
    json_output: bool = typer.Option(False, "--json", help="Emit metrics as JSON"),
    include_empty: bool = typer.Option(False, "--include-empty", help="Show caches with zero usage"),
    prime_netbox: bool = typer.Option(
        False, "--prime-netbox/--no-prime-netbox", help="Instantiate the NetBox client before sampling caches"
    ),
):
    """Print cache hit/miss metrics for registered TTL caches."""

    if prime_netbox:
        try:
            url = os.getenv("NETBOX_URL", "").strip()
            token = os.getenv("NETBOX_TOKEN", "").strip()
            if url and token:
                from infrastructure_atlas.infrastructure.external import NetboxClient, NetboxClientConfig

                NetboxClient(NetboxClientConfig(url=url, token=token))
            else:
                print("[yellow]NETBOX_URL/NETBOX_TOKEN not set; skipping NetBox cache priming[/yellow]")
        except Exception as exc:  # pragma: no cover - defensive logging
            print(f"[red]Failed to prime NetBox caches:[/red] {exc}")

    registry = get_cache_registry()
    snapshot = registry.snapshot()
    if not snapshot:
        print("[dim]No caches registered[/dim]")
        return

    if not include_empty:
        snapshot = {
            name: info
            for name, info in snapshot.items()
            if (info["metrics"].hits or info["metrics"].misses or info["metrics"].loads)
        }
        if not snapshot:
            print("[dim]No cache activity yet[/dim]")
            return

    if json_output:
        payload = {
            name: {
                "metrics": asdict(info["metrics"]),
                "size": info["size"],
                "ttl_seconds": info["ttl_seconds"],
            }
            for name, info in snapshot.items()
        }
        typer.echo(json.dumps(payload, indent=2, default=float))
        return

    table = Table(title="Cache Metrics")
    table.add_column("Cache", style="cyan")
    table.add_column("Hits", justify="right")
    table.add_column("Misses", justify="right")
    table.add_column("Loads", justify="right")
    table.add_column("Evictions", justify="right")
    table.add_column("Size", justify="right")
    table.add_column("TTL (s)", justify="right")

    for name in sorted(snapshot.keys()):
        info = snapshot[name]
        metrics = info["metrics"]
        table.add_row(
            name,
            str(metrics.hits),
            str(metrics.misses),
            str(metrics.loads),
            str(metrics.evictions),
            str(info["size"]),
            f"{info['ttl_seconds']:.0f}",
        )

    console.print(table)


def main() -> None:
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
