"""CLI helpers for vCenter inventory orchestration."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Annotated

import typer
from rich import print

from enreach_tools.application.services import create_vcenter_service
from enreach_tools.db import get_sessionmaker
from enreach_tools.db.setup import init_database
from enreach_tools.infrastructure.external import VCenterAuthError, VCenterClientError
from enreach_tools.infrastructure.security.secret_store import SecretStoreUnavailable

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
):
    """Refresh cached vCenter inventory for selected configurations."""

    init_database()
    SessionLocal = Sessionmaker()

    try:
        with SessionLocal as session:
            service = create_vcenter_service(session)
            targets = _select_configs(service, name or (), config_id or (), refresh_all)
            for config in targets:
                print(f"[cyan]Refreshing[/cyan] [bold]{config.name}[/bold] ({config.id})…", end=" ")
                try:
                    _, vms, meta = service.refresh_inventory(config.id)
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
    finally:
        SessionLocal.close()
