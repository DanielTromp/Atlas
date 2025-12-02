"""CLI helpers for Foreman configuration and inventory."""

from __future__ import annotations

import typer
from rich import print
from rich.table import Table

from infrastructure_atlas.application.services import create_foreman_service
from infrastructure_atlas.db import get_sessionmaker
from infrastructure_atlas.db.setup import init_database
from infrastructure_atlas.infrastructure.external import ForemanAuthError, ForemanClientError
from infrastructure_atlas.infrastructure.security.secret_store import SecretStoreUnavailable

HELP_CTX = {"help_option_names": ["-h", "--help"]}

app = typer.Typer(help="Foreman utilities", context_settings=HELP_CTX)

Sessionmaker = get_sessionmaker()


@app.command("list")
def list_configs():
    """List all Foreman configurations."""
    init_database()
    SessionLocal = Sessionmaker()

    try:
        with SessionLocal as session:
            service = create_foreman_service(session)
            configs = service.list_configs()

            if not configs:
                print("[yellow]No Foreman configurations found[/yellow]")
                return

            table = Table(title="Foreman Configurations")
            table.add_column("ID", style="cyan")
            table.add_column("Name", style="bold")
            table.add_column("URL", style="green")
            table.add_column("Username", style="blue")
            table.add_column("SSL Verify", style="yellow")

            for config in configs:
                table.add_row(
                    config.id,
                    config.name,
                    config.base_url,
                    config.username,
                    "Yes" if config.verify_ssl else "No",
                )

            print(table)
    finally:
        SessionLocal.close()


@app.command("create")
def create_config(
    name: str = typer.Option(..., "--name", "-n", help="Configuration name"),
    url: str = typer.Option(..., "--url", "-u", help="Foreman base URL"),
    username: str = typer.Option(
        None, "--username", help="Foreman username (required if token doesn't include username)"
    ),
    token: str = typer.Option(..., "--token", "-t", help="Personal Access Token (or 'username:token' format)"),
    verify_ssl: bool = typer.Option(True, "--verify-ssl/--no-verify-ssl", help="Verify SSL certificates"),
):
    """Create a new Foreman configuration."""
    init_database()
    SessionLocal = Sessionmaker()

    try:
        with SessionLocal as session:
            service = create_foreman_service(session)

            # Parse token - support both "token" and "username:token" formats
            parsed_username = username
            parsed_token = token

            if ":" in token and not username:
                # Token is in format "username:token"
                parts = token.split(":", 1)
                if len(parts) == 2:
                    parsed_username = parts[0]
                    parsed_token = parts[1]

            if not parsed_username:
                print("[red]✗[/red] Username is required. Either use --username or provide token as 'username:token'")
                raise typer.Exit(1)

            try:
                entity = service.create_config(
                    name=name,
                    base_url=url,
                    username=parsed_username,
                    token=parsed_token,
                    verify_ssl=verify_ssl,
                )
                print(f"[green]✓[/green] Created Foreman configuration [bold]{entity.name}[/bold] ({entity.id})")
            except SecretStoreUnavailable as exc:
                print(f"[red]✗[/red] Failed: {exc}")
                raise typer.Exit(1)
            except ValueError as exc:
                print(f"[red]✗[/red] Failed: {exc}")
                raise typer.Exit(1)
    finally:
        SessionLocal.close()


@app.command("update")
def update_config(
    config_id: str = typer.Argument(..., help="Configuration ID"),
    name: str | None = typer.Option(None, "--name", help="New name"),
    url: str | None = typer.Option(None, "--url", help="New base URL"),
    username: str | None = typer.Option(None, "--username", help="New username"),
    token: str | None = typer.Option(None, "--token", help="New Personal Access Token (or 'username:token' format)"),
    verify_ssl: bool | None = typer.Option(None, "--verify-ssl/--no-verify-ssl", help="Verify SSL certificates"),
):
    """Update an existing Foreman configuration."""
    init_database()
    SessionLocal = Sessionmaker()

    try:
        with SessionLocal as session:
            service = create_foreman_service(session)

            # Parse token if provided - support both "token" and "username:token" formats
            parsed_username = username
            parsed_token = token

            if token and ":" in token and not username:
                # Token is in format "username:token"
                parts = token.split(":", 1)
                if len(parts) == 2:
                    parsed_username = parts[0]
                    parsed_token = parts[1]

            try:
                entity = service.update_config(
                    config_id,
                    name=name,
                    base_url=url,
                    username=parsed_username,
                    token=parsed_token,
                    verify_ssl=verify_ssl,
                )
                print(f"[green]✓[/green] Updated Foreman configuration [bold]{entity.name}[/bold] ({entity.id})")
            except SecretStoreUnavailable as exc:
                print(f"[red]✗[/red] Failed: {exc}")
                raise typer.Exit(1)
            except ValueError as exc:
                print(f"[red]✗[/red] Failed: {exc}")
                raise typer.Exit(1)
    finally:
        SessionLocal.close()


@app.command("delete")
def delete_config(config_id: str = typer.Argument(..., help="Configuration ID")):
    """Delete a Foreman configuration."""
    init_database()
    SessionLocal = Sessionmaker()

    try:
        with SessionLocal as session:
            service = create_foreman_service(session)
            try:
                removed = service.delete_config(config_id)
                if removed:
                    print(f"[green]✓[/green] Deleted Foreman configuration {config_id}")
                else:
                    print(f"[yellow]Configuration {config_id} not found[/yellow]")
                    raise typer.Exit(1)
            except SecretStoreUnavailable as exc:
                print(f"[red]✗[/red] Failed: {exc}")
                raise typer.Exit(1)
    finally:
        SessionLocal.close()


@app.command("refresh")
def refresh_inventory(
    config_id: str = typer.Option(None, "--config-id", "-i", help="Configuration ID (optional, uses first if not provided)"),
):
    """Refresh Foreman hosts cache."""
    init_database()
    SessionLocal = Sessionmaker()

    try:
        with SessionLocal as session:
            service = create_foreman_service(session)

            # Get config
            if config_id:
                config = service.get_config(config_id)
                if not config:
                    print(f"[red]✗[/red] Configuration {config_id} not found")
                    raise typer.Exit(1)
            else:
                configs = service.list_configs()
                if not configs:
                    print("[yellow]No Foreman configurations found[/yellow]")
                    raise typer.Exit(1)
                config = configs[0]

            try:
                print(f"[cyan]Refreshing hosts from {config.name}...[/cyan]")
                _, hosts, meta = service.refresh_inventory(config.id)
                host_count = len(hosts)
                generated_at = meta.get("generated_at")
                if generated_at:
                    print(f"[green]✓[/green] Refreshed {host_count} hosts (cached at {generated_at})")
                else:
                    print(f"[green]✓[/green] Refreshed {host_count} hosts")
            except (ForemanAuthError, ForemanClientError) as exc:
                print(f"[red]✗[/red] API error: {exc}")
                raise typer.Exit(1)
            except ValueError as exc:
                print(f"[red]✗[/red] Error: {exc}")
                raise typer.Exit(1)
    finally:
        SessionLocal.close()


@app.command("test")
def test_connection(config_id: str = typer.Argument(..., help="Configuration ID")):
    """Test connectivity to a Foreman instance."""
    init_database()
    SessionLocal = Sessionmaker()

    try:
        with SessionLocal as session:
            service = create_foreman_service(session)
            try:
                result = service.test_connection(config_id)
                if result["status"] == "success":
                    print(f"[green]✓[/green] Successfully connected to {result['base_url']}")
                else:
                    print(f"[red]✗[/red] Connection failed: {result['message']}")
                    raise typer.Exit(1)
            except ValueError as exc:
                print(f"[red]✗[/red] Failed: {exc}")
                raise typer.Exit(1)
            except SecretStoreUnavailable as exc:
                print(f"[red]✗[/red] Failed: {exc}")
                raise typer.Exit(1)
    finally:
        SessionLocal.close()


@app.command("hosts")
def list_hosts(
    config_id: str | None = typer.Option(None, "--config-id", help="Configuration ID (uses first if not specified)"),
    search: str | None = typer.Option(None, "--search", help="Search query"),
):
    """List hosts from Foreman."""
    init_database()
    SessionLocal = Sessionmaker()

    try:
        with SessionLocal as session:
            service = create_foreman_service(session)

            # Get config
            if config_id:
                config = service.get_config(config_id)
                if not config:
                    print(f"[red]✗[/red] Configuration {config_id} not found")
                    raise typer.Exit(1)
            else:
                configs = service.list_configs()
                if not configs:
                    print("[yellow]No Foreman configurations found[/yellow]")
                    raise typer.Exit(1)
                config = configs[0]

            try:
                client = service.get_client(config.id)
                with client:
                    hosts = client.list_hosts(search=search)

                if not hosts:
                    print("[yellow]No hosts found[/yellow]")
                    return

                table = Table(title=f"Hosts from {config.name} ({len(hosts)} total)")
                table.add_column("ID", style="cyan")
                table.add_column("Name", style="bold")
                table.add_column("OS", style="cyan")
                table.add_column("Environment", style="green")
                table.add_column("Compute/Model", style="yellow")
                table.add_column("Hostgroup", style="blue")
                table.add_column("Last Report", style="dim")

                for host in hosts:
                    host_id = str(host.get("id") or "")
                    name = host.get("name") or ""
                    os = host.get("operatingsystem_name") or ""
                    env = host.get("environment_name") or ""
                    # Use compute_resource_name if available, otherwise model_name
                    compute_model = host.get("compute_resource_name") or host.get("model_name") or ""
                    hostgroup = host.get("hostgroup_name") or ""
                    last_report = host.get("last_report") or ""
                    # Format last_report to be more readable (remove UTC, show relative time if recent)
                    if last_report:
                        last_report = last_report.replace(" UTC", "")
                    table.add_row(host_id, name, os, env, compute_model, hostgroup, last_report)

                print(table)
                print(f"[green]✓[/green] Loaded {len(hosts)} hosts (cached for 5 minutes)")
            except (ForemanAuthError, ForemanClientError) as exc:
                print(f"[red]✗[/red] API error: {exc}")
                raise typer.Exit(1)
    finally:
        SessionLocal.close()


@app.command("show")
def show_host(
    host_id: str = typer.Argument(..., help="Host ID or name"),
    config_id: str | None = typer.Option(None, "--config-id", help="Configuration ID (uses first if not specified)"),
):
    """Show detailed information about a host including Puppet configuration."""
    init_database()
    SessionLocal = Sessionmaker()

    try:
        with SessionLocal as session:
            service = create_foreman_service(session)

            # Get config
            if config_id:
                config = service.get_config(config_id)
                if not config:
                    print(f"[red]✗[/red] Configuration {config_id} not found")
                    raise typer.Exit(1)
            else:
                configs = service.list_configs()
                if not configs:
                    print("[yellow]No Foreman configurations found[/yellow]")
                    raise typer.Exit(1)
                config = configs[0]

            try:
                client = service.get_client(config.id)
                with client:
                    host_detail = client.get_host_detail(host_id)
                    if not host_detail:
                        print(f"[red]✗[/red] Host {host_id} not found")
                        raise typer.Exit(1)

                    # Display basic info
                    print(f"[bold]Host:[/bold] {host_detail.get('name', host_id)}")
                    print(f"[bold]OS:[/bold] {host_detail.get('operatingsystem_name', 'N/A')}")
                    print(f"[bold]Environment:[/bold] {host_detail.get('environment_name', 'N/A')}")
                    print(f"[bold]Hostgroup:[/bold] {host_detail.get('hostgroup_name', 'N/A')}")
                    print(f"[bold]Last Report:[/bold] {host_detail.get('last_report', 'N/A')}")
                    print()

                    # Puppet status
                    puppet_status = host_detail.get("puppet_status")
                    puppet_proxy = host_detail.get("puppet_proxy_name") or "N/A"
                    puppet_ca = host_detail.get("puppet_ca_proxy_name") or "N/A"
                    print(f"[bold]Puppet Status:[/bold] {puppet_status}")
                    print(f"[bold]Puppet Proxy:[/bold] {puppet_proxy}")
                    print(f"[bold]Puppet CA Proxy:[/bold] {puppet_ca}")
                    print()

                    # Puppet classes
                    puppet_classes = client.get_host_puppet_classes(host_id)
                    if puppet_classes:
                        print(f"[bold]Puppet Classes ({len(puppet_classes)}):[/bold]")
                        for pclass in puppet_classes[:20]:  # Show first 20
                            class_name = pclass.get("name") or pclass.get("module_name") or ""
                            if class_name:
                                print(f"  - {class_name}")
                        if len(puppet_classes) > 20:
                            print(f"  ... and {len(puppet_classes) - 20} more")
                        print()

                    # Puppet parameters (user configs)
                    parameters = client.get_host_puppet_parameters(host_id)
                    if parameters:
                        print(f"[bold]Puppet Parameters ({len(parameters)}):[/bold]")
                        table = Table()
                        table.add_column("Name", style="cyan")
                        table.add_column("Value", style="green")
                        for param in parameters[:50]:  # Show first 50
                            param_name = param.get("name") or ""
                            param_value = str(param.get("value") or "")
                            # Truncate long values
                            if len(param_value) > 60:
                                param_value = param_value[:57] + "..."
                            table.add_row(param_name, param_value)
                        print(table)
                        if len(parameters) > 50:
                            print(f"[dim]... and {len(parameters) - 50} more parameters[/dim]")
                    else:
                        print("[yellow]No Puppet parameters found[/yellow]")

            except (ForemanAuthError, ForemanClientError) as exc:
                print(f"[red]✗[/red] API error: {exc}")
                raise typer.Exit(1)
    finally:
        SessionLocal.close()


@app.command("puppet-classes")
def list_puppet_classes(
    host_id: str = typer.Argument(..., help="Host ID or name"),
    config_id: str | None = typer.Option(None, "--config-id", help="Configuration ID (uses first if not specified)"),
):
    """List Puppet classes assigned to a host."""
    init_database()
    SessionLocal = Sessionmaker()

    try:
        with SessionLocal as session:
            service = create_foreman_service(session)

            # Get config
            if config_id:
                config = service.get_config(config_id)
                if not config:
                    print(f"[red]✗[/red] Configuration {config_id} not found")
                    raise typer.Exit(1)
            else:
                configs = service.list_configs()
                if not configs:
                    print("[yellow]No Foreman configurations found[/yellow]")
                    raise typer.Exit(1)
                config = configs[0]

            try:
                client = service.get_client(config.id)
                with client:
                    classes = client.get_host_puppet_classes(host_id)

                if not classes:
                    print("[yellow]No Puppet classes found[/yellow]")
                    return

                table = Table(title=f"Puppet Classes for Host {host_id} ({len(classes)} total)")
                table.add_column("ID", style="cyan")
                table.add_column("Name", style="bold")
                table.add_column("Module", style="green")

                for pclass in classes:
                    class_id = pclass.get("id") or ""
                    class_name = pclass.get("name") or ""
                    module_name = pclass.get("module_name") or ""
                    table.add_row(str(class_id), class_name, module_name)

                print(table)
                print(f"[green]✓[/green] Loaded {len(classes)} Puppet classes (cached for 5 minutes)")
            except (ForemanAuthError, ForemanClientError) as exc:
                print(f"[red]✗[/red] API error: {exc}")
                raise typer.Exit(1)
    finally:
        SessionLocal.close()


@app.command("puppet-parameters")
def list_puppet_parameters(
    host_id: str = typer.Argument(..., help="Host ID or name"),
    config_id: str | None = typer.Option(None, "--config-id", help="Configuration ID (uses first if not specified)"),
    search: str | None = typer.Option(None, "--search", help="Search parameter names"),
):
    """List Puppet parameters (user configs) for a host."""
    init_database()
    SessionLocal = Sessionmaker()

    try:
        with SessionLocal as session:
            service = create_foreman_service(session)

            # Get config
            if config_id:
                config = service.get_config(config_id)
                if not config:
                    print(f"[red]✗[/red] Configuration {config_id} not found")
                    raise typer.Exit(1)
            else:
                configs = service.list_configs()
                if not configs:
                    print("[yellow]No Foreman configurations found[/yellow]")
                    raise typer.Exit(1)
                config = configs[0]

            try:
                client = service.get_client(config.id)
                with client:
                    parameters = client.get_host_puppet_parameters(host_id)

                if not parameters:
                    print("[yellow]No Puppet parameters found[/yellow]")
                    return

                # Filter by search if provided
                if search:
                    search_lower = search.lower()
                    parameters = [p for p in parameters if search_lower in (p.get("name") or "").lower()]

                if not parameters:
                    print(f"[yellow]No parameters matching '{search}'[/yellow]")
                    return

                table = Table(title=f"Puppet Parameters for Host {host_id} ({len(parameters)} total)")
                table.add_column("Name", style="cyan", no_wrap=True)
                table.add_column("Value", style="green")

                for param in parameters:
                    param_name = param.get("name") or ""
                    param_value = str(param.get("value") or "")
                    # Truncate very long values for display
                    if len(param_value) > 100:
                        param_value = param_value[:97] + "..."
                    table.add_row(param_name, param_value)

                print(table)
                print(f"[green]✓[/green] Loaded {len(parameters)} parameters (cached for 5 minutes)")
            except (ForemanAuthError, ForemanClientError) as exc:
                print(f"[red]✗[/red] API error: {exc}")
                raise typer.Exit(1)
    finally:
        SessionLocal.close()


@app.command("puppet-facts")
def list_puppet_facts(
    host_id: str = typer.Argument(..., help="Host ID or name"),
    config_id: str | None = typer.Option(None, "--config-id", help="Configuration ID (uses first if not specified)"),
    search: str | None = typer.Option(None, "--search", help="Search fact names"),
    limit: int = typer.Option(100, "--limit", help="Maximum number of facts to display"),
):
    """List Puppet facts for a host."""
    init_database()
    SessionLocal = Sessionmaker()

    try:
        with SessionLocal as session:
            service = create_foreman_service(session)

            # Get config
            if config_id:
                config = service.get_config(config_id)
                if not config:
                    print(f"[red]✗[/red] Configuration {config_id} not found")
                    raise typer.Exit(1)
            else:
                configs = service.list_configs()
                if not configs:
                    print("[yellow]No Foreman configurations found[/yellow]")
                    raise typer.Exit(1)
                config = configs[0]

            try:
                client = service.get_client(config.id)
                with client:
                    facts = client.get_host_puppet_facts(host_id)

                if not facts:
                    print("[yellow]No Puppet facts found[/yellow]")
                    return

                # Filter by search if provided
                fact_items = list(facts.items())
                if search:
                    search_lower = search.lower()
                    fact_items = [(k, v) for k, v in fact_items if search_lower in k.lower()]

                if not fact_items:
                    print(f"[yellow]No facts matching '{search}'[/yellow]")
                    return

                # Sort by fact name
                fact_items.sort(key=lambda x: x[0])
                total_facts = len(fact_items)
                fact_items = fact_items[:limit]

                table = Table(title=f"Puppet Facts for Host {host_id} (showing {len(fact_items)} of {total_facts})")
                table.add_column("Fact Name", style="cyan", no_wrap=True)
                table.add_column("Value", style="green")

                for fact_name, fact_value in fact_items:
                    value_str = str(fact_value) if fact_value is not None else ""
                    # Truncate very long values
                    if len(value_str) > 100:
                        value_str = value_str[:97] + "..."
                    table.add_row(fact_name, value_str)

                print(table)
                if total_facts > limit:
                    print(f"[dim]Showing {limit} of {total_facts} facts. Use --limit to see more.[/dim]")
                print(f"[green]✓[/green] Loaded facts (cached for 5 minutes)")
            except (ForemanAuthError, ForemanClientError) as exc:
                print(f"[red]✗[/red] API error: {exc}")
                raise typer.Exit(1)
    finally:
        SessionLocal.close()
