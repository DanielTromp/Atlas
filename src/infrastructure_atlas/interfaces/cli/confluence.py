"""Confluence CLI commands."""

from __future__ import annotations

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
