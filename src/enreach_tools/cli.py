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
from .api.app import (
    zabbix_problems as zabbix_problems_api,
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

app = typer.Typer(help="Enreach Tools CLI", context_settings=HELP_CTX)

console = Console()
logger = get_logger(__name__)

try:
    AMS_TZ = ZoneInfo("Europe/Amsterdam")
except Exception:
    AMS_TZ = UTC

ZABBIX_SEVERITY_LABELS = [
    "Not classified",
    "Information",
    "Warning",
    "Average",
    "High",
    "Disaster",
]


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
        os.getenv("ENREACH_LOG_ACTOR"),
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
            "invoked_command": ctx.command_path or "enreach",
        },
    )


export = typer.Typer(help="Export helpers", context_settings=HELP_CTX)
app.add_typer(export, name="export")
api = typer.Typer(help="API server", context_settings=HELP_CTX)
app.add_typer(api, name="api")
zabbix = typer.Typer(help="Zabbix helpers", context_settings=HELP_CTX)
app.add_typer(zabbix, name="zabbix")
jira = typer.Typer(help="Jira helpers", context_settings=HELP_CTX)
app.add_typer(jira, name="jira")
confluence = typer.Typer(help="Confluence helpers", context_settings=HELP_CTX)
app.add_typer(confluence, name="confluence")
app.add_typer(commvault_cli_app, name="commvault")
app.add_typer(vcenter_cli_app, name="vcenter")
netbox = typer.Typer(help="NetBox helpers", context_settings=HELP_CTX)
app.add_typer(netbox, name="netbox")
tasks_cli = typer.Typer(help="Dataset cache tasks", context_settings=HELP_CTX)
app.add_typer(tasks_cli, name="tasks")
search = typer.Typer(help="Cross-system search aggregator", context_settings=HELP_CTX)
app.add_typer(search, name="search")
db = typer.Typer(help="Database utilities", context_settings=HELP_CTX)
app.add_typer(db, name="db")
users_cli = typer.Typer(help="User administration helpers", context_settings=HELP_CTX)
app.add_typer(users_cli, name="users")


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


def _severity_label(level: object) -> str:
    idx = max(0, min(len(ZABBIX_SEVERITY_LABELS) - 1, _safe_int(level, 0)))
    return ZABBIX_SEVERITY_LABELS[idx]


def _zbx_dedupe_key(item: dict[str, object]) -> str:
    name = str(item.get("name") or "").strip()
    prefix = name.split(":", 1)[0].strip() if ":" in name else name
    host_key = str(item.get("hostid") or item.get("host") or "").strip()
    if host_key and prefix:
        return f"{host_key}|{prefix}"
    if host_key:
        return f"{host_key}|{name}"
    if prefix:
        event = str(item.get("eventid") or "").strip()
        return f"{prefix}|{event}"
    return str(item.get("eventid") or "").strip()


@tasks_cli.command("refresh")
def tasks_refresh(
    dataset_ids: Annotated[
        list[str] | None,
        typer.Argument(
            ...,
            metavar="DATASET",
            help="Dataset identifier(s) to refresh (default: all).",
        ),
    ] = None,
    list_only: bool = typer.Option(False, "--list", help="List available datasets."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show commands without executing them."),
):
    """Refresh cached datasets used by the Tasks dashboard."""

    definitions = _collect_task_dataset_definitions()
    if not definitions:
        print("[yellow]No dataset tasks are defined.[/yellow]")
        raise typer.Exit(code=0)

    dataset_map = {definition.id: definition for definition in definitions}

    if list_only:
        table = Table(title="Dataset tasks")
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Label")
        table.add_column("Files", justify="right", no_wrap=True)
        table.add_column("Last Updated", justify="right")
        table.add_column("Command", overflow="fold")
        for definition in definitions:
            meta = _build_dataset_metadata(definition)
            command = _build_dataset_command(definition, meta)
            updated = meta.last_updated.isoformat() if meta.last_updated else "—"
            present = sum(1 for record in meta.files if record.exists)
            files = f"{present}/{len(meta.files)}"
            command_display = shlex.join(command) if command else "—"
            table.add_row(
                definition.id,
                definition.label or definition.id,
                files,
                updated,
                command_display,
            )
        console.print(table)
        raise typer.Exit(code=0)

    if dataset_ids:
        missing = [identifier for identifier in dataset_ids if identifier not in dataset_map]
        if missing:
            print(f"[red]Unknown dataset id(s):[/red] {', '.join(missing)}")
            raise typer.Exit(code=1)
        targets = [dataset_map[identifier] for identifier in dataset_ids]
    else:
        targets = list(definitions)

    if not targets:
        print("[yellow]No matching datasets selected.[/yellow]")
        raise typer.Exit(code=0)

    failures = 0
    ran_any = False
    for definition in targets:
        meta = _build_dataset_metadata(definition)
        command = _build_dataset_command(definition, meta)
        label = definition.label or definition.id
        if not command:
            print(f"[yellow]Skipping[/yellow] {label} ({definition.id}) — no command configured.")
            continue
        command_display = shlex.join(command)
        if dry_run:
            print(f"[cyan]{definition.id}[/cyan] {command_display}")
            ran_any = True
            continue
        print(f"[cyan]Running[/cyan] {definition.id} → {command_display}")
        start = monotonic()
        rc = subprocess.call(command, cwd=str(project_root()))
        duration = monotonic() - start
        if rc != 0:
            failures += 1
            print(f"[red]Failed[/red] (exit {rc}) after {duration:.1f}s")
        else:
            ran_any = True
            print(f"[green]Completed[/green] in {duration:.1f}s")

    if not ran_any:
        print("[yellow]No commands were executed.[/yellow]")
    if failures and not dry_run:
        raise typer.Exit(code=1)


def _apply_zabbix_gui_filter(
    items: Sequence[dict[str, object]], *, unack_only: bool
) -> list[dict[str, object]]:
    buckets: dict[str, dict[str, object]] = {}
    for item in items:
        key = _zbx_dedupe_key(item)
        existing = buckets.get(key)
        if not existing:
            buckets[key] = item
            continue
        prev_sev = _safe_int(existing.get("severity"), -1)
        cur_sev = _safe_int(item.get("severity"), -1)
        if cur_sev > prev_sev:
            buckets[key] = item
            continue
        if cur_sev < prev_sev:
            continue
        prev_clock = _safe_int(existing.get("clock"), 0)
        cur_clock = _safe_int(item.get("clock"), 0)
        if cur_clock >= prev_clock:
            buckets[key] = item

    deduped = list(buckets.values())
    if unack_only:
        deduped = [it for it in deduped if _safe_int(it.get("acknowledged"), 0) == 0]
    deduped.sort(key=lambda it: _safe_int(it.get("clock"), 0), reverse=True)
    return deduped


def _format_zabbix_time(item: dict[str, object]) -> str:
    iso_value = str(item.get("clock_iso") or "").strip()
    dt: datetime | None = None
    if iso_value:
        try:
            dt = datetime.fromisoformat(iso_value.replace(" ", "T"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
        except Exception:
            dt = None
    if dt is None:
        clock = _safe_int(item.get("clock"), 0)
        if clock:
            try:
                dt = datetime.fromtimestamp(clock, tz=UTC)
            except Exception:
                dt = None
    if dt is None:
        return iso_value or ""
    local_dt = dt.astimezone(AMS_TZ)
    today = datetime.now(AMS_TZ).date()
    if local_dt.date() == today:
        return local_dt.strftime("%H:%M:%S")
    return local_dt.strftime("%Y-%m-%d %H:%M:%S")


def _format_zabbix_duration(clock: int) -> str:
    now_ts = int(datetime.now(UTC).timestamp())
    seconds = max(0, now_ts - max(0, clock))
    days, remainder = divmod(seconds, 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minutes, seconds = divmod(remainder, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if not days and not hours:
        parts.append(f"{seconds}s")
    return " ".join(parts) if parts else "0s"


def _service_context() -> ServiceContext:
    return ServiceContext(session_factory=get_sessionmaker())


def _echo_json_dicts(items: Iterable[dict]) -> None:
    typer.echo(json.dumps(list(items), indent=2))


@users_cli.command("list")
def users_list(
    include_inactive: bool = typer.Option(False, "--include-inactive", help="Include inactive users"),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
):
    """List users in the internal authentication database."""
    ctx = _service_context()
    with ctx.session_scope() as session:
        service = create_admin_service(session)
        entities = service.list_users(include_inactive=include_inactive)
    dtos = admin_users_to_dto(entities)
    payload = [dto.model_dump(mode="json") for dto in dtos]
    if json_output:
        _echo_json_dicts(payload)
        return
    if not payload:
        print("[yellow]No users found[/yellow]")
        return
    table = Table(title="Users")
    table.add_column("Username", style="cyan")
    table.add_column("Role", style="magenta")
    table.add_column("Active", style="green")
    table.add_column("Email")
    table.add_column("Display Name")
    for dto in dtos:
        table.add_row(
            dto.username,
            dto.role,
            "yes" if dto.is_active else "no",
            dto.email or "-",
            dto.display_name or "-",
        )
    console.print(table)


@users_cli.command("create")
def users_create(
    username: str = typer.Argument(..., help="Username (will be normalised to lowercase)"),
    password: str = typer.Option(..., "--password", help="Initial password (min length 8)"),
    role: str = typer.Option("member", "--role", help="User role"),
    display_name: str = typer.Option("", "--display-name", help="Optional display name"),
    email: str = typer.Option("", "--email", help="Optional email address"),
    json_output: bool = typer.Option(False, "--json", help="Output result as JSON"),
):
    """Create a new user."""
    username_norm = username.strip().lower()
    if not username_norm:
        print("[red]Username is required[/red]")
        raise typer.Exit(code=1)
    if len(password.strip()) < 8:
        print("[red]Password must be at least 8 characters[/red]")
        raise typer.Exit(code=1)
    role_norm = (role or "member").strip().lower() or "member"

    ctx = _service_context()
    with ctx.session_scope() as session:
        service = create_admin_service(session)
        available_roles = {rp.role for rp in service.list_role_permissions()}
        if role_norm not in available_roles:
            formatted = ", ".join(sorted(available_roles)) or "(no roles defined)"
            print(f"[red]Role '{role_norm}' is not defined[/red]")
            print(f"[dim]Available roles:[/dim] {formatted}")
            raise typer.Exit(code=1)
        try:
            service.ensure_username_available(username_norm)
        except ValueError as exc:
            print(f"[red]{exc}[/red]")
            raise typer.Exit(code=1) from exc
        entity = service.create_user(
            username=username_norm,
            password=password.strip(),
            display_name=display_name or None,
            email=email or None,
            role=role_norm,
        )
    dto = admin_user_to_dto(entity)
    if json_output:
        _echo_json_dicts([dto.model_dump(mode="json")])
    else:
        print(f"[green]Created user[/green] {dto.username} ({dto.role})")


@users_cli.command("set-password")
def users_set_password(
    username: str = typer.Argument(..., help="Username"),
    password: str = typer.Option(..., "--password", help="New password (min length 8)"),
):
    """Set or reset a user's password."""
    username_norm = username.strip().lower()
    new_password = password.strip()
    if len(new_password) < 8:
        print("[red]Password must be at least 8 characters[/red]")
        raise typer.Exit(code=1)

    ctx = _service_context()
    with ctx.session_scope() as session:
        service = create_admin_service(session)
        user = service.get_user_by_username(username_norm)
        if user is None:
            print(f"[red]User '{username_norm}' not found[/red]")
            raise typer.Exit(code=1)
        service.set_password(user, new_password)
    print(f"[green]Password updated for[/green] {username_norm}")


@export.command("cache")
def netbox_cache(
    force: bool = typer.Option(False, "--force", help="Force refresh from NetBox and bypass in-memory cache"),
    verbose: bool = typer.Option(False, "--verbose/--no-verbose", help="Log detailed cache diff results"),
):
    """Refresh the NetBox JSON cache without rewriting CSV or Excel exports."""

    require_env(["NETBOX_URL", "NETBOX_TOKEN"])
    if tracing_enabled():
        init_tracing("enreach-cli")
    with logging_context(command="export.cache", force=force, verbose=verbose), span(
        "cli.export.cache", force=force, verbose=verbose
    ):
        service = NetboxExportService.from_env()
        result = service.refresh_cache(force=force, verbose=verbose)
        print(f"[green]Cache updated[/green] {result.path.as_posix()}")
        timestamp = result.generated_at.astimezone().isoformat(timespec="seconds")
        print(f"[dim]Generated at:[/dim] {timestamp}")
        summaries = result.summaries
        if not summaries:
            print("[yellow]No cacheable resources were returned[/yellow]")
            return
        for name, summary in summaries.items():
            diffs: list[str] = []
            if summary.added:
                diffs.append(f"{summary.added} new")
            if summary.updated:
                diffs.append(f"{summary.updated} updated")
            if summary.removed:
                diffs.append(f"{summary.removed} removed")
            diff_label = ", ".join(diffs) if diffs else "no changes"
            print(
                f"[cyan]{name}[/cyan]: {summary.total} total ({diff_label})",
            )


@export.command("devices")
def netbox_devices(
    force: bool = typer.Option(False, "--force", help="Re-fetch all devices and rewrite CSV"),
):
    """Export devices to CSV (incremental)."""
    require_env(["NETBOX_URL", "NETBOX_TOKEN"])
    args = ["--force"] if force else []
    raise_code = _run_script("netbox-export/bin/get_netbox_devices.py", *args)
    raise SystemExit(raise_code)


@export.command("vms")
def netbox_vms(
    force: bool = typer.Option(False, "--force", help="Re-fetch all VMs and rewrite CSV"),
):
    """Export VMs to CSV (incremental)."""
    require_env(["NETBOX_URL", "NETBOX_TOKEN"])
    args = ["--force"] if force else []
    raise_code = _run_script("netbox-export/bin/get_netbox_vms.py", *args)
    raise SystemExit(raise_code)


@export.command("merge")
def netbox_merge():
    """Merge devices+vms CSV into a single CSV and Excel."""
    raise_code = _run_script("netbox-export/bin/merge_netbox_csvs.py")
    raise SystemExit(raise_code)


@app.command("status")
def netbox_status():
    """Check API status and token access (200/403 details)."""
    code = _run_script("netbox-export/bin/netbox_status.py")
    raise SystemExit(code)


def _auto_publish_after_export() -> None:
    """Publish NetBox exports to Confluence when env vars are configured."""

    logger.info("Checking Confluence auto-publish configuration")
    try:
        base = os.getenv("ATLASSIAN_BASE_URL", "").strip()
        email = os.getenv("ATLASSIAN_EMAIL", "").strip()
        token = os.getenv("ATLASSIAN_API_TOKEN", "").strip()
        page_id = os.getenv("CONFLUENCE_CMDB_PAGE_ID", "").strip() or os.getenv("CONFLUENCE_PAGE_ID", "").strip()
        devices_page_id = os.getenv("CONFLUENCE_DEVICES_PAGE_ID", "").strip() or page_id
        vms_page_id = os.getenv("CONFLUENCE_VMS_PAGE_ID", "").strip() or os.getenv("CONFLUENCE_PAGE_ID", "").strip()
        if base and email and token and page_id:
            logger.info("Publishing CMDB export to Confluence", extra={"page_id": page_id})
            _ = _run_script("netbox-export/bin/confluence_publish_cmdb.py", "--page-id", page_id)
            table_args: list[str] = []
            if devices_page_id:
                table_args += ["--page-id", devices_page_id]
            _ = _run_script("netbox-export/bin/confluence_publish_devices_table.py", *table_args)
            vms_args: list[str] = []
            if vms_page_id:
                vms_args += ["--page-id", vms_page_id]
            _ = _run_script("netbox-export/bin/confluence_publish_vms_table.py", *vms_args)
        else:
            print("[dim]Confluence not configured; skipping auto publish[/dim]")
            logger.debug("Confluence auto-publish skipped", extra={"base": base, "page_id": page_id})
    except Exception as exc:  # pragma: no cover - CLI helper
        print(f"[red]Confluence publish failed:[/red] {exc}")
        logger.exception("Confluence auto-publish failed")


@export.command("update")
def netbox_update(
    force: bool = typer.Option(False, "--force", help="Re-fetch all devices and VMs before merge"),
    use_queue: bool = typer.Option(False, "--queue/--no-queue", help="Schedule export via the in-memory job queue"),
    legacy: bool = typer.Option(False, "--legacy/--no-legacy", help="Use legacy exporter scripts"),
    verbose: bool = typer.Option(False, "--verbose/--no-verbose", help="Log verbose exporter progress"),
    refresh_cache: bool = typer.Option(
        True,
        "--refresh-cache/--no-refresh-cache",
        help="Refresh the NetBox JSON cache before exporting (disable to reuse the existing snapshot)",
    ),
):
    """Run devices, vms, then merge exports in sequence."""
    require_env(["NETBOX_URL", "NETBOX_TOKEN"])  # token needed for export endpoints
    mode = "queue" if use_queue else "legacy"
    if tracing_enabled():
        init_tracing("enreach-cli")
    previous_legacy = os.environ.get("ENREACH_LEGACY_EXPORTER")
    if legacy:
        os.environ["ENREACH_LEGACY_EXPORTER"] = "1"
    with logging_context(command="export.update", mode=mode, force=force, verbose=verbose), span(
        "cli.export.update", mode=mode, force=force, verbose=verbose
    ):
        logger.info("NetBox export command invoked")
        if verbose:
            logger.info("Verbose exporter output enabled")
        if use_queue:
            service = NetboxExportService.from_env()
            queue = InMemoryJobQueue()
            runner = AsyncJobRunner(queue)
            runner.register_handler(service.JOB_NAME, service.job_handler())

            async def _run_job() -> JobStatus:
                await runner.start()
                try:
                    build_kwargs = {"force": force, "verbose": verbose}
                    try:
                        spec_signature = inspect.signature(service.build_job_spec)
                    except (TypeError, ValueError):
                        spec_signature = None
                    if spec_signature and "refresh_cache" in spec_signature.parameters:
                        build_kwargs["refresh_cache"] = refresh_cache
                    record = await queue.enqueue(service.build_job_spec(**build_kwargs))
                    while True:
                        job = await queue.get_job(record.job_id)
                        if job and job.status in {JobStatus.COMPLETED, JobStatus.FAILED}:
                            return job.status
                        await asyncio.sleep(0.2)
                finally:
                    await runner.stop()

            status = asyncio.run(_run_job())
            logger.info("Queued NetBox export finished", extra={"status": status})
            if status != JobStatus.COMPLETED:
                print("[red]Queued NetBox export failed[/red]")
                raise typer.Exit(code=1)
        else:
            start = monotonic()
            status = "success"
            args = ["--force"] if force else []
            if verbose:
                args.append("--verbose")
            if not refresh_cache:
                args.append("--no-refresh-cache")
            try:
                code = _run_script("netbox-export/bin/netbox_update.py", *args)
                if code != 0:
                    status = "failure"
                    raise SystemExit(code)
            except Exception:
                status = "failure"
                duration = monotonic() - start
                record_netbox_export(duration_seconds=duration, mode="legacy", force=force, status=status)
                logger.exception("Legacy NetBox export failed", extra={"duration_ms": int(duration * 1000)})
                raise
            else:
                duration = monotonic() - start
                record_netbox_export(duration_seconds=duration, mode="legacy", force=force, status=status)
                logger.info("Legacy NetBox export completed", extra={"duration_ms": int(duration * 1000)})

        _auto_publish_after_export()
    if legacy:
        if previous_legacy is None:
            os.environ.pop("ENREACH_LEGACY_EXPORTER", None)
        else:
            os.environ["ENREACH_LEGACY_EXPORTER"] = previous_legacy


@app.command("cache-stats")
def cache_stats(
    json_output: bool = typer.Option(False, "--json", help="Emit metrics as JSON"),
    include_empty: bool = typer.Option(False, "--include-empty", help="Show caches with zero usage"),
    prime_netbox: bool = typer.Option(False, "--prime-netbox/--no-prime-netbox", help="Instantiate the NetBox client before sampling caches"),
):
    """Print cache hit/miss metrics for registered TTL caches."""

    if prime_netbox:
        try:
            url = os.getenv("NETBOX_URL", "").strip()
            token = os.getenv("NETBOX_TOKEN", "").strip()
            if url and token:
                from enreach_tools.infrastructure.external import NetboxClient, NetboxClientConfig

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


@api.command("serve")
def api_serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host"),
    port: int = typer.Option(8000, "--port", help="Bind port"),
    reload: bool = typer.Option(True, "--reload/--no-reload", help="Auto-reload on changes"),
    log_level: str = typer.Option("", "--log-level", help="Uvicorn log level (overrides LOG_LEVEL env)"),
    ssl_certfile: str | None = typer.Option(
        None,
        "--ssl-certfile",
        help="Path to SSL certificate (PEM). If omitted, uses ENREACH_SSL_CERTFILE when set.",
    ),
    ssl_keyfile: str | None = typer.Option(
        None,
        "--ssl-keyfile",
        help="Path to SSL private key (PEM). If omitted, uses ENREACH_SSL_KEYFILE when set.",
    ),
    ssl_keyfile_password: str | None = typer.Option(
        None,
        "--ssl-keyfile-password",
        help="Password for encrypted SSL keyfile (optional). If omitted, uses ENREACH_SSL_KEY_PASSWORD when set.",
        show_default=False,
    ),
):
    """Run the FastAPI server (HTTP or HTTPS).

    Provide --ssl-certfile/--ssl-keyfile (or ENREACH_SSL_CERTFILE/ENREACH_SSL_KEYFILE)
    to enable HTTPS. When not provided, server runs over HTTP.
    """
    import uvicorn

    # Resolve SSL params from env when not explicitly provided
    ssl_certfile = ssl_certfile or os.getenv("ENREACH_SSL_CERTFILE") or None
    ssl_keyfile = ssl_keyfile or os.getenv("ENREACH_SSL_KEYFILE") or None
    ssl_keyfile_password = ssl_keyfile_password or os.getenv("ENREACH_SSL_KEY_PASSWORD") or None

    resolved_log_level = (log_level or os.getenv("LOG_LEVEL") or "warning").lower()

    kwargs: dict = {"host": host, "port": port, "reload": reload, "log_level": resolved_log_level}
    if ssl_certfile and ssl_keyfile:
        kwargs.update(
            {
                "ssl_certfile": ssl_certfile,
                "ssl_keyfile": ssl_keyfile,
            }
        )
        if ssl_keyfile_password:
            kwargs["ssl_keyfile_password"] = ssl_keyfile_password

    # ASGI app path: src/enreach_tools/api/app.py -> app
    uvicorn.run("enreach_tools.api.app:app", **kwargs)


@db.command("init")
def db_init(echo: bool = typer.Option(False, "--echo", help="Echo SQL while running migrations")):
    """Initialise or upgrade the application database using Alembic."""
    if echo:
        os.environ["SQLALCHEMY_ECHO"] = "1"
    init_database()
    print("[green]Database initialised[/green]")


@zabbix.command("dashboard")
def zabbix_dashboard_cli(
    groupids: str = typer.Option("", "--groupids", help="Comma-separated host group IDs (e.g. 27)."),
    hostids: str = typer.Option("", "--hostids", help="Comma-separated host IDs."),
    severities: str = typer.Option("", "--severities", help="Comma-separated severities 0-5 (defaults to UI config)."),
    include_subgroups: bool = typer.Option(True, "--include-subgroups/--no-include-subgroups", help="When filtering by group IDs, include all subgroups."),
    limit: int = typer.Option(300, "--limit", help="Maximum rows to fetch from the API (1-2000)."),
    unack_only: bool = typer.Option(False, "--unack-only/--include-acked", help="Match the UI toggle by filtering for unacknowledged problems after deduplication."),
    systems_only: bool = typer.Option(False, "--systems-only/--all-groups", help="Shortcut for Systems group (ID 27) including subgroups."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON payload instead of a table."),
):
    """Show the same Zabbix dashboard feed as the web UI."""

    load_env()

    gid_value = groupids.strip().strip(",")
    if systems_only:
        gid_value = gid_value or "27"
        include_subgroups = True

    host_value = hostids.strip().strip(",") or None
    sev_value = severities.strip().strip(",") or None
    gid_value_opt = gid_value or None

    include_subgroups_flag = 1 if include_subgroups and gid_value_opt else 0

    try:
        payload = zabbix_problems_api(
            severities=sev_value,
            groupids=gid_value_opt,
            hostids=host_value,
            unacknowledged=0,
            suppressed=0,
            limit=limit,
            include_subgroups=include_subgroups_flag,
        )
    except HTTPException as exc:  # pragma: no cover - runtime API failure path
        detail = exc.detail if isinstance(exc.detail, str) else json.dumps(exc.detail)
        print(f"[red]Zabbix API error:[/red] {detail}")
        raise typer.Exit(code=1)

    items = payload.get("items", [])
    filtered = _apply_zabbix_gui_filter(items, unack_only=unack_only)

    if json_output:
        typer.echo(json.dumps({"items": filtered, "count": len(filtered)}, indent=2))
        return

    if not filtered:
        print("[yellow]No problems to show[/yellow]")
        return

    table = Table(title="Zabbix Dashboard")
    table.add_column("Time", style="cyan")
    table.add_column("Severity", style="magenta")
    table.add_column("Status", style="green")
    table.add_column("Host", style="blue")
    table.add_column("Problem")
    table.add_column("Duration", style="dim")

    for item in filtered:
        time_text = _format_zabbix_time(item)
        severity_text = _severity_label(item.get("severity"))
        status_raw = (item.get("status") or "").upper() or "PROBLEM"
        if _safe_int(item.get("acknowledged"), 0):
            status_text = f"{status_raw} [dim](ack)[/dim]"
        else:
            status_text = status_raw
        host = str(item.get("host") or "-" )
        problem_name = str(item.get("name") or "")
        prob_url = str(item.get("problem_url") or "").strip()
        if prob_url:
            problem_cell = f"[link={prob_url}]{problem_name}[/link]"
        else:
            problem_cell = problem_name
        duration = _format_zabbix_duration(_safe_int(item.get("clock"), 0))
        table.add_row(time_text, severity_text, status_text, host, problem_cell, duration)

    console.print(table)
    raw_count = payload.get("count", len(items))
    summary_parts = [f"{len(filtered)} shown", f"raw {len(items)}"]
    if raw_count != len(items):
        summary_parts.append(f"API count {raw_count}")
    if unack_only:
        summary_parts.append("unacknowledged only")
    if gid_value_opt:
        summary_parts.append(f"group(s) {gid_value_opt}{' +sub' if include_subgroups_flag else ''}")
    print(f"[dim]{' — '.join(summary_parts)}[/dim]")


@zabbix.command("problems")
def zabbix_problems_cli(
    limit: int = typer.Option(20, "--limit", help="Max items"),
    severities: str = typer.Option("", "--severities", help="Comma list, e.g. 2,3,4 (defaults from .env)"),
    groupids: str = typer.Option("", "--groupids", help="Comma list group IDs (default from .env)"),
    include_all: bool = typer.Option(False, "--all", help="Include acknowledged (unacknowledged=0)"),
):
    """Fetch problems from Zabbix via JSON-RPC and print a summary."""
    import requests as _rq
    from rich import print as _print

    from .env import load_env as _load

    _load()
    base = os.getenv("ZABBIX_API_URL", "").strip() or os.getenv("ZABBIX_HOST", "").strip()
    if not base:
        _print("[red]ZABBIX_API_URL or ZABBIX_HOST not set[/red]")
        raise SystemExit(1)
    if not base.endswith("/api_jsonrpc.php"):
        base = base.rstrip("/") + "/api_jsonrpc.php"
    token = os.getenv("ZABBIX_API_TOKEN", "").strip()
    if not token:
        _print("[yellow]Warning:[/yellow] ZABBIX_API_TOKEN not set; request may be unauthorized")

    def _rpc(method: str, params: dict) -> dict:
        body = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
        if token:
            body["auth"] = token
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        r = _rq.post(base, headers=headers, json=body, timeout=30)
        r.raise_for_status()
        data = r.json()
        if data.get("error"):
            raise RuntimeError(f"Zabbix error: {data['error']}")
        return data.get("result", {})

    # Params
    sev_list = []
    if severities.strip():
        try:
            sev_list = [int(x) for x in severities.split(",") if x.strip()]
        except Exception:
            pass
    elif os.getenv("ZABBIX_SEVERITIES", "").strip():
        try:
            sev_list = [int(x) for x in os.getenv("ZABBIX_SEVERITIES").split(",") if x.strip()]
        except Exception:
            pass
    grp_list = []
    if groupids.strip():
        try:
            grp_list = [int(x) for x in groupids.split(",") if x.strip()]
        except Exception:
            pass
    elif os.getenv("ZABBIX_GROUP_ID", "").strip().isdigit():
        grp_list = [int(os.getenv("ZABBIX_GROUP_ID").strip())]

    params = {
        "output": ["eventid", "name", "severity", "clock", "acknowledged", "r_eventid", "source", "object", "objectid"],
        "selectTags": "extend",
        "recent": True,
        "limit": int(limit),
    }
    if sev_list:
        params["severities"] = sev_list
    if grp_list:
        params["groupids"] = grp_list
    # Default: show only unacknowledged; when --all, remove filter to show both
    if not include_all:
        params["acknowledged"] = 0

    try:
        res = _rpc("problem.get", params)
    except Exception as ex:
        _print(f"[red]Request failed:[/red] {ex}")
        raise SystemExit(1)

    items = res if isinstance(res, list) else []
    items.sort(key=lambda x: int(x.get("clock") or 0), reverse=True)
    _print(f"[bold]Problems:[/bold] {len(items)} (showing up to {limit})")
    from datetime import datetime as _dt
    for it in items[: limit]:
        clk = int(it.get("clock") or 0)
        ts = _dt.utcfromtimestamp(clk).strftime("%Y-%m-%d %H:%M:%S") if clk else "?"
        sev = int(it.get("severity") or 0)
        name = it.get("name") or ""
        _print(f"- [{ts}] sev={sev} {name}")


@zabbix.command("search")
def zabbix_search_cli(
    q: str = typer.Option(..., "--q", help="Substring to match in host name or problem name (wildcards enabled)"),
    limit: int = typer.Option(200, "--limit", help="Max items per call (200 typical)"),
):
    """Probe Zabbix for hosts, interfaces, problems and events matching a query.

    This mirrors the fuzzy logic used by the Search aggregator:
    - host.get search on both name and host with wildcards
    - hostinterface.get by IP when q looks like an IPv4
    - problem.get by hostids or fallback by name search with wildcards
    - event.get by hostids or fallback by name search with wildcards
    """
    import re as _re

    import requests as _rq
    from rich import print as _print

    from .env import load_env as _load

    _load()
    base = os.getenv("ZABBIX_API_URL", "").strip() or os.getenv("ZABBIX_HOST", "").strip()
    if not base:
        _print("[red]ZABBIX_API_URL or ZABBIX_HOST not set[/red]")
        raise SystemExit(1)
    if not base.endswith("/api_jsonrpc.php"):
        base = base.rstrip("/") + "/api_jsonrpc.php"
    token = os.getenv("ZABBIX_API_TOKEN", "").strip()
    if not token:
        _print("[yellow]Warning:[/yellow] ZABBIX_API_TOKEN not set; request may be unauthorized")

    def _rpc(method: str, params: dict) -> dict:
        body = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
        if token:
            body["auth"] = token
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        r = _rq.post(base, headers=headers, json=body, timeout=30)
        r.raise_for_status()
        data = r.json()
        if data.get("error"):
            raise RuntimeError(f"Zabbix error: {data['error']}")
        return data.get("result", {})

    patt = f"*{q}*"
    # 1) Find matching hosts
    hosts = _rpc(
        "host.get",
        {
            "output": ["hostid", "host", "name"],
            "search": {"name": patt, "host": patt},
            "searchByAny": 1,
            "searchWildcardsEnabled": 1,
            "limit": int(limit),
        },
    ) or []
    hostids = []
    for h in hosts:
        try:
            hostids.append(int(h.get("hostid")))
        except Exception:
            pass
    # 1b) If q looks like IPv4, search interfaces by IP
    if _re.match(r"^\d{1,3}(?:\.\d{1,3}){3}$", q.strip()):
        try:
            intfs = _rpc("hostinterface.get", {"output": ["interfaceid", "hostid", "ip"], "search": {"ip": q.strip()}, "limit": int(limit)}) or []
            for itf in intfs:
                try:
                    hostids.append(int(itf.get("hostid")))
                except Exception:
                    pass
        except Exception:
            pass
    hostids = sorted({i for i in hostids if isinstance(i, int)})
    _print(f"[bold]Hosts:[/bold] {len(hostids)} matches")
    for h in hosts:
        _print(f"- id={h.get('hostid')} host={h.get('host')} name={h.get('name')}")

    # 2) Active problems
    p_params = {
        "output": ["eventid", "name", "severity", "clock", "acknowledged", "r_eventid"],
        "selectHosts": ["host", "name", "hostid"],
        "limit": int(limit),
        # Some installations disallow API sort by 'clock'; sort client-side instead
    }
    if hostids:
        p_params["hostids"] = hostids
    else:
        p_params["search"] = {"name": patt}
        p_params["searchWildcardsEnabled"] = 1
    problems = _rpc("problem.get", p_params) or []
    # Sort client-side by clock desc when present
    try:
        problems.sort(key=lambda x: int(x.get("clock") or 0), reverse=True)
    except Exception:
        pass
    _print(f"[bold]Problems:[/bold] {len(problems)} matches")
    for it in problems:
        clk = int(it.get("clock") or 0)
        from datetime import datetime as _dt
        ts = _dt.utcfromtimestamp(clk).strftime("%Y-%m-%d %H:%M:%S") if clk else "?"
        sev = it.get("severity")
        nm = it.get("name")
        hosts_disp = ", ".join([f"{h.get('host') or h.get('name')}" for h in (it.get('hosts') or [])])
        status = "ACTIVE" if str(it.get("r_eventid") or "").strip() in ("", "0") else "RESOLVED"
        _print(f"- [{ts}] [{status}] sev={sev} {nm} [dim]({hosts_disp})[/dim]")

    # 3) Historical events
    ev_params = {
        "output": ["eventid", "name", "clock", "value"],
        "selectHosts": ["host", "name", "hostid"],
        "source": 0,
        "limit": int(limit),
        # Sort client-side (some servers disallow sorting by 'clock')
    }
    if hostids:
        ev_params["hostids"] = hostids
    else:
        ev_params["search"] = {"name": patt}
        ev_params["searchWildcardsEnabled"] = 1
    events = _rpc("event.get", ev_params) or []
    try:
        events.sort(key=lambda x: int(x.get("clock") or 0), reverse=True)
    except Exception:
        pass
    _print(f"[bold]Events:[/bold] {len(events)} matches")
    for it in events[: min(len(events), 10)]:
        clk = int(it.get("clock") or 0)
        from datetime import datetime as _dt
        ts = _dt.utcfromtimestamp(clk).strftime("%Y-%m-%d %H:%M:%S") if clk else "?"
        nm = it.get("name")
        ev_status = "PROBLEM" if str(it.get("value") or "").strip() == "1" else "OK"
        hosts_disp = ", ".join([f"{h.get('host') or h.get('name')}" for h in (it.get('hosts') or [])])
        _print(f"- [{ts}] [{ev_status}] {nm} [dim]({hosts_disp})[/dim]")


@jira.command("search")
def jira_search_cli(
    q: str = typer.Option("", "--q", help="Full-text query (text ~ '...')"),
    jql: str = typer.Option("", "--jql", help="Explicit JQL (overrides filters)"),
    project: str = typer.Option("", "--project", help="Project key or name"),
    status: str = typer.Option("", "--status", help="Comma-separated statuses"),
    assignee: str = typer.Option("", "--assignee", help="Assignee (name/email)"),
    priority: str = typer.Option("", "--priority", help="Priority or list"),
    issuetype: str = typer.Option("", "--type", help="Issue type"),
    team: str = typer.Option("Systems Infrastructure", "--team", help="Team (Service Desk) name"),
    updated: str = typer.Option("-30d", "--updated", help="-7d, -30d or YYYY-MM-DD"),
    only_open: bool = typer.Option(True, "--open/--all", help="Open only (statusCategory != Done)"),
    max_results: int = typer.Option(25, "--max", help="Max results (<=200)"),
):
    """Search Jira issues and print a concise list."""
    load_env()
    from enreach_tools.api.app import jira_search as _js
    res = _js(
        q=(q or None),
        jql=(jql or None),
        project=(project or None),
        status=(status or None),
        assignee=(assignee or None),
        priority=(priority or None),
        issuetype=(issuetype or None),
        updated=(updated or None),
        team=(team or None),
        only_open=1 if only_open else 0,
        max_results=max_results,
    )
    from rich import print as _print
    _print(f"[bold]JQL:[/bold] {res.get('jql','')}")
    issues = res.get("issues", [])
    for it in issues:
        _print(f"- [link={it.get('url','')}]" +
               f"{it.get('key','')}[/link] | {it.get('status','')} | {it.get('assignee','') or '-'} | {it.get('priority','') or '-'} | {it.get('summary','')}")
    _print(f"[dim]{len(issues)} shown (total {res.get('total', len(issues))})[/dim]")


@confluence.command("search")
def confluence_search_cli(
    q: str = typer.Option("", "--q", help="Full-text query (text ~ '...')"),
    space: str = typer.Option("", "--space", help="Space key or exact space name (comma-separated allowed)"),
    ctype: str = typer.Option("page", "--type", help="page|blogpost|attachment"),
    labels: str = typer.Option("", "--labels", help="Comma-separated labels"),
    updated: str = typer.Option("", "--updated", help="-7d, -30d, -90d or YYYY-MM-DD"),
    max_results: int = typer.Option(25, "--max", help="Max results (<=100)"),
):
    """Search Confluence content and print a concise list."""
    load_env()
    from enreach_tools.api.app import confluence_search as _cs
    res = _cs(
        q=(q or None),
        space=(space or None),
        ctype=(ctype or None),
        labels=(labels or None),
        updated=(updated or None),
        max_results=max_results,
    )
    from rich import print as _print
    _print(f"[bold]CQL:[/bold] {res.get('cql','')}")
    items = res.get("results", [])
    for it in items:
        _print(f"- [link={it.get('url','')}]" +
               f"{it.get('title','')}[/link] | {it.get('space','') or '-'} | {it.get('type','')} | {it.get('updated','') or '-'}")
    _print(f"[dim]{len(items)} shown (total {res.get('total', len(items))})[/dim]")


@confluence.command("upload")
def confluence_upload(
    file: str = typer.Option(
        "data/Systems CMDB.xlsx",
        "--file",
        help="Local file to upload",
    ),
    page_id: str = typer.Option(
        "",
        "--page-id",
        help="Target Confluence page ID (defaults to CONFLUENCE_CMDB_PAGE_ID)",
    ),
    name: str = typer.Option("", "--name", help="Attachment name (defaults to source filename)"),
    comment: str = typer.Option("", "--comment", help="Attachment version comment"),
):
    """Upload or replace an attachment on a Confluence page."""
    args = ["--file", file]
    if page_id:
        args += ["--page-id", page_id]
    if name:
        args += ["--name", name]
    if comment:
        args += ["--comment", comment]
    code = _run_script("netbox-export/bin/confluence_upload_attachment.py", *args)
    raise SystemExit(code)


def main():  # entry point for console_scripts
    app()


@confluence.command("publish-cmdb")
def confluence_publish_cmdb(
    page_id: str = typer.Option("", "--page-id", help="Override target page ID"),
    name: str = typer.Option("Systems CMDB.xlsx", "--name", help="Attachment name"),
    comment: str = typer.Option("", "--comment", help="Attachment version comment"),
):
    """Publish the standard NetBox CMDB Excel to Confluence."""
    args: list[str] = []
    if page_id:
        args += ["--page-id", page_id]
    if name:
        args += ["--name", name]
    if comment:
        args += ["--comment", comment]
    code = _run_script("netbox-export/bin/confluence_publish_cmdb.py", *args)
    raise SystemExit(code)


@confluence.command("publish-devices-table")
def confluence_publish_devices_table(
    csv: str = typer.Option(
        "data/netbox_devices_export.csv",
        "--csv",
        help="Path to the NetBox devices CSV",
    ),
    page_id: str = typer.Option("", "--page-id", help="Target Confluence page ID"),
    heading: str = typer.Option("NetBox Devices Export", "--heading", help="Heading placed above the table"),
    limit: int | None = typer.Option(None, "--limit", help="Limit number of rows (defaults to all)"),
    filter_macro: bool | None = typer.Option(None, "--filter/--no-filter", help="Wrap in Table Filter macro"),
    sort_macro: bool | None = typer.Option(None, "--sort/--no-sort", help="Wrap in Table Sort macro"),
    message: str = typer.Option("Updated NetBox devices table", "--message", help="Confluence version comment"),
    minor: bool = typer.Option(True, "--minor/--major", help="Mark update as minor edit"),
):
    """Publish the devices CSV as a Confluence table (with optional filter/sort macros)."""
    if filter_macro is None:
        filter_macro = _env_flag("CONFLUENCE_ENABLE_TABLE_FILTER", False)
    if sort_macro is None:
        sort_macro = _env_flag("CONFLUENCE_ENABLE_TABLE_SORT", False)
    args: list[str] = ["--csv", csv]
    if page_id:
        args += ["--page-id", page_id]
    if heading:
        args += ["--heading", heading]
    if limit is not None:
        args += ["--limit", str(limit)]
    args.append("--filter" if filter_macro else "--no-filter")
    args.append("--sort" if sort_macro else "--no-sort")
    if message:
        args += ["--message", message]
    if not minor:
        args.append("--major")
    code = _run_script("netbox-export/bin/confluence_publish_devices_table.py", *args)
    raise SystemExit(code)


@confluence.command("publish-vms-table")
def confluence_publish_vms_table(
    csv: str = typer.Option(
        "data/netbox_vms_export.csv",
        "--csv",
        help="Path to the NetBox VMs CSV",
    ),
    page_id: str = typer.Option("", "--page-id", help="Target Confluence page ID"),
    heading: str = typer.Option("NetBox VMs Export", "--heading", help="Heading placed above the table"),
    limit: int | None = typer.Option(None, "--limit", help="Limit number of rows (defaults to all)"),
    filter_macro: bool | None = typer.Option(None, "--filter/--no-filter", help="Wrap in Table Filter macro"),
    sort_macro: bool | None = typer.Option(None, "--sort/--no-sort", help="Wrap in Table Sort macro"),
    message: str = typer.Option("Updated NetBox VMs table", "--message", help="Confluence version comment"),
    minor: bool = typer.Option(True, "--minor/--major", help="Mark update as minor edit"),
):
    """Publish the VMs CSV as a Confluence table (with optional filter/sort macros)."""
    if filter_macro is None:
        filter_macro = _env_flag("CONFLUENCE_ENABLE_TABLE_FILTER", False)
    if sort_macro is None:
        sort_macro = _env_flag("CONFLUENCE_ENABLE_TABLE_SORT", False)
    args: list[str] = ["--csv", csv]
    if page_id:
        args += ["--page-id", page_id]
    if heading:
        args += ["--heading", heading]
    if limit is not None:
        args += ["--limit", str(limit)]
    args.append("--filter" if filter_macro else "--no-filter")
    args.append("--sort" if sort_macro else "--no-sort")
    if message:
        args += ["--message", message]
    if not minor:
        args.append("--major")
    code = _run_script("netbox-export/bin/confluence_publish_vms_table.py", *args)
    raise SystemExit(code)


@netbox.command("search")
def netbox_search_cli(
    q: str = typer.Option(..., "--q", help="Full-text query"),
    dataset: str = typer.Option("all", "--dataset", help="all|devices|vms"),
    limit: int = typer.Option(50, "--limit", help="0 = no limit (fetch all pages)"),
):
    """Search NetBox live via the API (no CSV)."""
    load_env()
    from enreach_tools.api.app import netbox_search as _nb
    if dataset not in ("all", "devices", "vms"):
        print("[red]dataset must be one of: all, devices, vms[/red]")
        raise SystemExit(2)
    res = _nb(dataset=dataset, q=q, limit=limit)
    from rich import print as _print
    _print({k: res.get(k) for k in ("total",)})
    for row in res.get("rows", []):
        name = row.get("Name", "")
        typ = row.get("Type", "")
        status = row.get("Status", "")
        primary = row.get("Primary IP", "")
        oob = row.get("Out-of-band IP", "")
        _print(f"- {name} [dim]({typ or 'n/a'})[/dim] — {status} — {primary or oob or '-'}")


@netbox.command("device-json")
def netbox_device_json(
    device_id: int = typer.Option(0, "--id", help="Device ID"),
    name: str = typer.Option("", "--name", help="Device name (exact) if --id not used"),
    raw: bool = typer.Option(False, "--raw", help="Print raw JSON only"),
):
    """Fetch full JSON for a device from NetBox and print it."""
    import requests as _rq
    load_env()
    base = os.getenv("NETBOX_URL", "").strip()
    token = os.getenv("NETBOX_TOKEN", "").strip()
    if not base or not token:
        print("[red]NETBOX_URL/NETBOX_TOKEN not configured[/red]")
        raise SystemExit(2)
    base = base.rstrip('/')
    sess = _rq.Session()
    sess.headers.update({"Authorization": f"Token {token}", "Accept": "application/json"})
    def _get(u: str):
        r = sess.get(u, timeout=30)
        r.raise_for_status()
        return r.json()
    data = None
    if device_id:
        data = _get(f"{base}/api/dcim/devices/{device_id}/")
    else:
        if not name:
            print("[red]Provide --id or --name[/red]")
            raise SystemExit(2)
        js = _get(f"{base}/api/dcim/devices/?name={name}")
        results = js.get("results", []) if isinstance(js, dict) else []
        if not results:
            print(f"[red]Not found:[/red] {name}")
            raise SystemExit(1)
        data = results[0]
    if raw:
        import json as _json
        print(_json.dumps(data, indent=2))
    else:
        from rich import print_json as _pjson
        _pjson(data=data)


@search.command("run")
def search_run(
    q: str = typer.Option(..., "--q", "-q", help="Object name or keyword (e.g. device, vm, IP, substring)"),
    zlimit: int = typer.Option(0, "--zlimit", help="Zabbix max items (0 = no limit)"),
    jlimit: int = typer.Option(0, "--jlimit", help="Jira max issues (0 = no limit)"),
    climit: int = typer.Option(0, "--climit", help="Confluence max results (0 = no limit)"),
    json_out: bool = typer.Option(False, "--json", help="Output full JSON with all available fields"),
    out: str = typer.Option("", "--out", help="Save full JSON to file (pretty-printed)"),
):
    """Run the Search aggregator across Zabbix, Jira, Confluence, and NetBox.

    Defaults: unlimited (zlimit/jlimit/climit = 0). Use --json for full details.
    """
    load_env()
    logger.info(
        "Search CLI invoked",
        extra={
            "query": q,
            "zlimit": zlimit,
            "jlimit": jlimit,
            "climit": climit,
            "json": json_out,
            "out": out or None,
        },
    )
    from enreach_tools.api.app import search_aggregate as _agg
    res = _agg(q=q, zlimit=zlimit, jlimit=jlimit, climit=climit)
    # Save to file when requested (pretty JSON)
    if out:
        import json as _json
        import pathlib as _pl
        path = _pl.Path(out)
        try:
            path.write_text(_json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[green]Saved:[/green] {path}")
        except Exception as e:
            print(f"[red]Failed to write {path}:[/red] {e}")
    if json_out:
        import json as _json
        print(_json.dumps(res, ensure_ascii=False, indent=2))
        return
    from rich import print as _print
    _print(f"[bold]Search:[/bold] '{q}'")
    # Zabbix
    z = res.get("zabbix") or {}
    _print(f"[bold]Zabbix[/bold] — active: {len(z.get('active') or [])}, historical: {len(z.get('historical') or [])}")
    for it in (z.get("active") or [])[:10]:
        _print(f"  - [{it.get('clock','')}] [{it.get('status','')}] sev={it.get('severity','')} {it.get('name','')}")
    # Jira
    j = res.get("jira") or {}
    _print(f"[bold]Jira[/bold] — {j.get('total', 0)} issues")
    for it in (j.get("issues") or [])[:10]:
        _print(f"  - {it.get('key','')} {it.get('summary','')} [dim]{it.get('updated','')}[/dim]")
    # Confluence
    c = res.get("confluence") or {}
    _print(f"[bold]Confluence[/bold] — {c.get('total', 0)} pages")
    for it in (c.get("results") or [])[:10]:
        _print(f"  - {it.get('title','')} [dim]{it.get('updated','')}[/dim]")
    # NetBox
    n = res.get("netbox") or {}
    _print(f"[bold]NetBox[/bold] — {n.get('total', 0)} items")
    for it in (n.get("items") or [])[:10]:
        nm = it.get('Name') or ''
        typ = it.get('Type') or ''
        upd = it.get('Updated') or ''
        _print(f"  - {nm} {f'({typ})' if typ else ''} [dim]{upd}[/dim]")
