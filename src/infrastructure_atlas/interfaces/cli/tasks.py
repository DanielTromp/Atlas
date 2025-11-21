"""Tasks CLI commands - dataset cache management."""

from __future__ import annotations

import shlex
import subprocess
from time import monotonic

import typer
from rich import print as _print
from rich.console import Console
from rich.table import Table

from infrastructure_atlas.env import load_env, project_root
from infrastructure_atlas.interfaces.shared.tasks import (
    _build_dataset_command,
    _build_dataset_metadata,
    _collect_task_dataset_definitions,
)

app = typer.Typer(help="Dataset cache tasks", context_settings={"help_option_names": ["-h", "--help"]})
console = Console()


@app.command("refresh")
def tasks_refresh(
    dataset_ids: list[str] | None = typer.Argument(
        None,
        metavar="DATASET",
        help="Dataset identifier(s) to refresh (default: all).",
    ),
    list_only: bool = typer.Option(False, "--list", help="List available datasets."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show commands without executing them."),
):
    """Refresh cached datasets used by the Tasks dashboard."""
    load_env()

    definitions = _collect_task_dataset_definitions()
    if not definitions:
        _print("[yellow]No dataset tasks are defined.[/yellow]")
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
            _print(f"[red]Unknown dataset id(s):[/red] {', '.join(missing)}")
            raise typer.Exit(code=1)
        targets = [dataset_map[identifier] for identifier in dataset_ids]
    else:
        targets = list(definitions)

    if not targets:
        _print("[yellow]No matching datasets selected.[/yellow]")
        raise typer.Exit(code=0)

    failures = 0
    ran_any = False
    for definition in targets:
        meta = _build_dataset_metadata(definition)
        command = _build_dataset_command(definition, meta)
        label = definition.label or definition.id
        if not command:
            _print(f"[yellow]Skipping[/yellow] {label} ({definition.id}) — no command configured.")
            continue
        command_display = shlex.join(command)
        if dry_run:
            _print(f"[cyan]{definition.id}[/cyan] {command_display}")
            ran_any = True
            continue
        _print(f"[cyan]Running[/cyan] {definition.id} → {command_display}")
        start = monotonic()
        rc = subprocess.call(command, cwd=str(project_root()))
        duration = monotonic() - start
        if rc != 0:
            failures += 1
            _print(f"[red]Failed[/red] (exit {rc}) after {duration:.1f}s")
        else:
            ran_any = True
            _print(f"[green]Completed[/green] in {duration:.1f}s")

    if not ran_any:
        _print("[yellow]No commands were executed.[/yellow]")
    if failures and not dry_run:
        raise typer.Exit(code=1)
