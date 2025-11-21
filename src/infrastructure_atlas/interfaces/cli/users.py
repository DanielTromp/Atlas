"""User administration CLI commands."""

from __future__ import annotations

import json
from collections.abc import Iterable

import typer
from rich import print
from rich.console import Console
from rich.table import Table

from infrastructure_atlas.application.context import ServiceContext
from infrastructure_atlas.application.dto.admin import admin_user_to_dto, admin_users_to_dto
from infrastructure_atlas.application.services import create_admin_service
from infrastructure_atlas.db import get_sessionmaker

app = typer.Typer(help="User administration helpers", context_settings={"help_option_names": ["-h", "--help"]})
console = Console()


def _service_context() -> ServiceContext:
    """Create a service context with database session factory."""
    return ServiceContext(session_factory=get_sessionmaker())


def _echo_json_dicts(items: Iterable[dict]) -> None:
    """Output a list of dictionaries as JSON."""
    typer.echo(json.dumps(list(items), indent=2))


@app.command("list")
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


@app.command("create")
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


@app.command("set-password")
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
