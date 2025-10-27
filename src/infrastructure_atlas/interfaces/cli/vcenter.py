"""CLI helpers for vCenter inventory orchestration."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Annotated

import typer
from rich import print

from infrastructure_atlas.application.services import create_vcenter_service
from infrastructure_atlas.db import get_sessionmaker
from infrastructure_atlas.db.setup import init_database
from infrastructure_atlas.infrastructure.external import VCenterAuthError, VCenterClientError
from infrastructure_atlas.infrastructure.security.secret_store import SecretStoreUnavailable

HELP_CTX = {"help_option_names": ["-h", "--help"]}

app = typer.Typer(help="vCenter utilities", context_settings=HELP_CTX)

Sessionmaker = get_sessionmaker()


def _select_configs(service, names: Iterable[str], ids: Iterable[str], refresh_all: bool):
    configs = service.list_configs()
    if refresh_all:
        return configs

    name_filters = {name.strip().lower() for name in names if isinstance(name, str) and name.strip()}
    id_filters = {identifier.strip() for identifier in ids if isinstance(identifier, str) and identifier.strip()}

    if not name_filters and not id_filters:
        raise typer.BadParameter("Provide at least one --name/--id or use --all to refresh every vCenter.")

    selected = []
    for config in configs:
        if config.id in id_filters or config.id.lower() in id_filters:
            selected.append(config)
            continue
        if config.name and config.name.lower() in name_filters:
            selected.append(config)
    if not selected:
        raise typer.BadParameter("No vCenter configurations matched the provided filters.")
    return selected


@app.command("refresh")
def refresh_inventory(
    name: Annotated[
        list[str] | None,
        typer.Option("--name", "-n", help="Refresh vCenters with a matching name (repeatable).", show_default=False),
    ] = None,
    config_id: Annotated[
        list[str] | None,
        typer.Option("--id", help="Refresh specific vCenter configuration IDs.", show_default=False),
    ] = None,
    refresh_all: Annotated[bool, typer.Option("--all", help="Refresh every configured vCenter.", show_default=False)] = False,
    vm: Annotated[
        list[str] | None,
        typer.Option(
            "--vm",
            "-V",
            help="Limit refresh to the specified VM IDs (repeatable).",
            show_default=False,
        ),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            "-v",
            help="Show detailed placement coverage for each refreshed vCenter.",
            show_default=False,
        ),
    ] = False,
):
    """Refresh cached vCenter inventory for selected configurations."""

    init_database()
    SessionLocal = Sessionmaker()

    try:
        with SessionLocal as session:
            service = create_vcenter_service(session)
            targets = _select_configs(service, name or (), config_id or (), refresh_all)
            vm_filters = {item.strip().lower() for item in vm or [] if isinstance(item, str)} or None
            for config in targets:
                print(f"[cyan]Refreshing[/cyan] [bold]{config.name}[/bold] ({config.id})…", end=" ")
                try:
                    _, vms, meta = service.refresh_inventory(config.id, vm_ids=vm_filters)
                except SecretStoreUnavailable as exc:
                    print(f"[red]skipped[/red] (secrets unavailable: {exc})")
                    continue
                except VCenterAuthError as exc:
                    print(f"[red]failed[/red] (authentication error: {exc})")
                    continue
                except VCenterClientError as exc:
                    print(f"[red]failed[/red] ({exc})")
                    continue

                generated_at = meta.get("generated_at")
                timestamp = (
                    generated_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
                    if isinstance(generated_at, datetime)
                    else "unknown"
                )
                vm_total = meta.get("vm_count") or len(vms)
                print(f"[green]done[/green] ({vm_total} VMs @ {timestamp})")

                if verbose and vms:
                    placement_fields = (
                        ("host", "Host"),
                        ("cluster", "Cluster"),
                        ("datacenter", "Datacenter"),
                        ("resource_pool", "Resource Pool"),
                        ("folder", "Folder"),
                    )
                    coverage_parts = []
                    for attr, label in placement_fields:
                        missing = sum(1 for vm in vms if not getattr(vm, attr))
                        coverage_parts.append(f"{label}: {vm_total - missing}/{vm_total}")
                    print(f"    [dim]Placement coverage[/dim]: {', '.join(coverage_parts)}")

                    missing_example = next(
                        (vm for vm in vms if any(not getattr(vm, attr) for attr, _ in placement_fields)),
                        None,
                    )
                    if missing_example:
                        values = []
                        for attr, label in placement_fields:
                            value = getattr(missing_example, attr)
                            values.append(f"{label}={value or '—'}")
                        print(
                            "    [dim]Example missing placement[/dim]: "
                            f"{missing_example.name or missing_example.vm_id} ({', '.join(values)})"
                        )
                        raw_detail = getattr(missing_example, "raw_detail", None)
                        if isinstance(raw_detail, dict):
                            placement_raw = raw_detail.get("placement")
                            if placement_raw:
                                print(f"    [dim]Raw placement payload[/dim]: {placement_raw}")
                        raw_summary = getattr(missing_example, "raw_summary", None)
                        if isinstance(raw_summary, dict):
                            summary_keys = {k: raw_summary.get(k) for k in ("host", "cluster", "datacenter", "resource_pool", "folder") if k in raw_summary}
                            if summary_keys:
                                print(f"    [dim]Summary fields[/dim]: {summary_keys}")
    finally:
        SessionLocal.close()
