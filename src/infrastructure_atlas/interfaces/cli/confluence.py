"""Confluence CLI commands."""

from __future__ import annotations

import os
import sys
import typer
from rich import print as _print

from infrastructure_atlas.env import load_env
from infrastructure_atlas.infrastructure.modules import get_module_registry

app = typer.Typer(help="Confluence helpers", context_settings={"help_option_names": ["-h", "--help"]})


@app.callback(invoke_without_command=True)
def check_module_enabled(ctx: typer.Context):
    """Ensure Confluence module is enabled before running commands."""
    if ctx.invoked_subcommand:
        registry = get_module_registry()
        try:
            registry.require_enabled("confluence")
        except Exception as e:
            _print(f"[red]Confluence module is disabled:[/red] {e}")
            raise typer.Exit(code=1)


def _env_flag(key: str, default: bool = False) -> bool:
    """Parse boolean from environment variable."""
    val = os.getenv(key, "").strip().lower()
    if val in ("1", "true", "yes", "on"):
        return True
    if val in ("0", "false", "no", "off"):
        return False
    return default


def _run_script(script_path: str, *args: str) -> int:
    """Run a Python script with arguments."""
    import subprocess

    cmd = [sys.executable, script_path, *args]
    try:
        result = subprocess.run(cmd, check=False)
        return result.returncode
    except Exception as e:
        _print(f"[red]Error running script:[/red] {e}")
        return 1


@app.command("search")
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
    # Import the route function from api routes
    from infrastructure_atlas.interfaces.api.routes.confluence import confluence_search as _cs

    res = _cs(
        q=(q or None),
        space=(space or None),
        ctype=(ctype or None),
        labels=(labels or None),
        updated=(updated or None),
        max_results=max_results,
    )
    _print(f"[bold]CQL:[/bold] {res.get('cql','')}")
    items = res.get("results", [])
    for it in items:
        _print(
            f"- [link={it.get('url','')}]"
            + f"{it.get('title','')}[/link] | {it.get('space','') or '-'} | {it.get('type','')} | {it.get('updated','') or '-'}"
        )
    _print(f"[dim]{len(items)} shown (total {res.get('total', len(items))})[/dim]")


@app.command("upload")
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


@app.command("publish-cmdb")
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


@app.command("publish-devices-table")
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


@app.command("publish-vms-table")
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
