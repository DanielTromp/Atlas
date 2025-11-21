"""Jira CLI commands."""

from __future__ import annotations

import typer
from rich import print as _print

from infrastructure_atlas.env import load_env
from infrastructure_atlas.infrastructure.logging import get_logger
from infrastructure_atlas.infrastructure.modules import get_module_registry

logger = get_logger(__name__)

app = typer.Typer(help="Jira helpers")


@app.callback(invoke_without_command=True)
def check_module_enabled(ctx: typer.Context):
    """Ensure Jira module is enabled before running commands."""
    if ctx.invoked_subcommand:
        registry = get_module_registry()
        try:
            registry.require_enabled("jira")
        except Exception as e:
            _print(f"[red]Jira module is disabled:[/red] {e}")
            raise typer.Exit(code=1)


@app.command("search")
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
    from infrastructure_atlas.api.app import jira_search as _js

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
    _print(f"[bold]JQL:[/bold] {res.get('jql', '')}")
    issues = res.get("issues", [])
    for it in issues:
        _print(
            f"- [link={it.get('url', '')}]"
            + f"{it.get('key', '')}[/link] | {it.get('status', '')} | {it.get('assignee', '') or '-'} | {it.get('priority', '') or '-'} | {it.get('summary', '')}"
        )
    _print(f"[dim]{len(issues)} shown (total {res.get('total', len(issues))})[/dim]")
