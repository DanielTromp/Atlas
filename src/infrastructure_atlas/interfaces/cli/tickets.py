"""CLI commands for draft ticket management.

Draft tickets are AI-proposed tickets that can be reviewed, approved, and pushed to Jira.
They serve as a staging area for ticket proposals before they become official Jira issues.
"""

from __future__ import annotations

from typing import Annotated

import typer
from rich import print
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from infrastructure_atlas.application.services import (
    DraftTicketNotFoundError,
    DraftTicketService,
    DraftTicketValidationError,
    create_draft_ticket_service,
)
from infrastructure_atlas.domain.draft_tickets import DraftTicketStatus

HELP_CTX = {"help_option_names": ["-h", "--help"]}

app = typer.Typer(help="Draft ticket management", context_settings=HELP_CTX)
console = Console()


def _get_service() -> DraftTicketService:
    """Get a draft ticket service instance."""
    return create_draft_ticket_service()


def _status_color(status: DraftTicketStatus) -> str:
    """Get the color for a status."""
    colors = {
        DraftTicketStatus.PROPOSED: "yellow",
        DraftTicketStatus.APPROVED: "green",
        DraftTicketStatus.PUSHED: "blue",
        DraftTicketStatus.REJECTED: "red",
    }
    return colors.get(status, "white")


def _priority_color(priority: str) -> str:
    """Get the color for a priority."""
    colors = {
        "critical": "red",
        "high": "orange1",
        "medium": "yellow",
        "low": "green",
    }
    return colors.get(priority.lower(), "white")


@app.command("list")
def list_tickets(
    status: Annotated[
        str | None,
        typer.Option(
            "--status",
            "-s",
            help="Filter by status (proposed, approved, pushed, rejected)",
        ),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Show detailed information"),
    ] = False,
):
    """List all draft tickets."""
    service = _get_service()

    try:
        tickets = service.list_all(status_filter=status)
    except Exception as exc:
        print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    if not tickets:
        print("[yellow]No draft tickets found.[/yellow]")
        return

    # Show counts
    counts = service.get_counts_by_status()
    print(
        f"\n[dim]Total: {sum(counts.values())} tickets "
        f"([yellow]proposed: {counts.get('proposed', 0)}[/yellow], "
        f"[green]approved: {counts.get('approved', 0)}[/green], "
        f"[blue]pushed: {counts.get('pushed', 0)}[/blue], "
        f"[red]rejected: {counts.get('rejected', 0)}[/red])[/dim]\n"
    )

    table = Table(show_header=True, header_style="bold")
    table.add_column("ID", style="dim", width=8)
    table.add_column("Title", width=40)
    table.add_column("Priority", width=10)
    table.add_column("Status", width=10)
    table.add_column("Linked Jira", width=12)

    if verbose:
        table.add_column("Created", width=20)
        table.add_column("Reviewed By", width=15)

    for ticket in tickets:
        status_color = _status_color(ticket.status)
        priority_color = _priority_color(ticket.suggested_priority.value)

        row = [
            ticket.id[:8],
            ticket.suggested_title[:40] + ("..." if len(ticket.suggested_title) > 40 else ""),
            f"[{priority_color}]{ticket.suggested_priority.value}[/{priority_color}]",
            f"[{status_color}]{ticket.status.value}[/{status_color}]",
            ticket.linked_jira_key or "-",
        ]

        if verbose:
            created_str = ticket.created_at.strftime("%Y-%m-%d %H:%M") if ticket.created_at else "-"
            row.extend([created_str, ticket.reviewed_by or "-"])

        table.add_row(*row)

    console.print(table)


@app.command("show")
def show_ticket(
    ticket_id: Annotated[str, typer.Argument(help="Draft ticket ID (full or partial)")],
):
    """Show details of a draft ticket."""
    service = _get_service()

    # Try to find the ticket by partial ID
    tickets = service.list_all()
    matches = [t for t in tickets if t.id.startswith(ticket_id)]

    if not matches:
        print(f"[red]No ticket found matching ID: {ticket_id}[/red]")
        raise typer.Exit(1)

    if len(matches) > 1:
        print(f"[yellow]Multiple tickets match '{ticket_id}':[/yellow]")
        for ticket in matches:
            print(f"  - {ticket.id}: {ticket.suggested_title}")
        raise typer.Exit(1)

    ticket = matches[0]
    status_color = _status_color(ticket.status)
    priority_color = _priority_color(ticket.suggested_priority.value)

    # Build panel content
    content = []
    content.append(f"[bold]Title:[/bold] {ticket.suggested_title}")
    content.append(f"[bold]Priority:[/bold] [{priority_color}]{ticket.suggested_priority.value}[/{priority_color}]")
    content.append(f"[bold]Status:[/bold] [{status_color}]{ticket.status.value}[/{status_color}]")

    if ticket.suggested_labels:
        content.append(f"[bold]Labels:[/bold] {', '.join(ticket.suggested_labels)}")

    if ticket.suggested_description:
        content.append(f"\n[bold]Description:[/bold]\n{ticket.suggested_description}")

    if ticket.ai_proposal:
        content.append(f"\n[bold]AI Proposal:[/bold]\n{ticket.ai_proposal}")

    if ticket.linked_jira_key:
        content.append(f"\n[bold]Linked Jira:[/bold] {ticket.linked_jira_key} ({ticket.link_type.value if ticket.link_type else 'relates_to'})")
        content.append(f"[bold]Jira URL:[/bold] {ticket.linked_jira_url}")

    if ticket.created_jira_key:
        content.append(f"\n[bold]Created Jira:[/bold] {ticket.created_jira_key}")
        content.append(f"[bold]Jira URL:[/bold] {ticket.created_jira_url}")
        if ticket.pushed_to_jira_at:
            content.append(f"[bold]Pushed At:[/bold] {ticket.pushed_to_jira_at.strftime('%Y-%m-%d %H:%M:%S')}")

    if ticket.source_context:
        content.append(f"\n[bold]Source Context:[/bold]\n{ticket.source_context}")

    content.append(f"\n[dim]ID: {ticket.id}[/dim]")
    content.append(f"[dim]Created: {ticket.created_at.strftime('%Y-%m-%d %H:%M:%S')}[/dim]")
    content.append(f"[dim]Updated: {ticket.updated_at.strftime('%Y-%m-%d %H:%M:%S')}[/dim]")

    if ticket.reviewed_by:
        content.append(f"[dim]Reviewed by: {ticket.reviewed_by}[/dim]")
    if ticket.reviewed_at:
        content.append(f"[dim]Reviewed at: {ticket.reviewed_at.strftime('%Y-%m-%d %H:%M:%S')}[/dim]")

    panel = Panel(
        "\n".join(content),
        title=f"Draft Ticket [{ticket.id[:8]}]",
        border_style=status_color,
    )
    console.print(panel)


@app.command("create")
def create_ticket(
    title: Annotated[str, typer.Option("--title", "-t", help="Ticket title", prompt=True)],
    description: Annotated[
        str | None,
        typer.Option("--description", "-d", help="Ticket description"),
    ] = None,
    priority: Annotated[
        str,
        typer.Option("--priority", "-p", help="Priority (low, medium, high, critical)"),
    ] = "medium",
    labels: Annotated[
        list[str] | None,
        typer.Option("--label", "-l", help="Labels (can be repeated)"),
    ] = None,
    linked_jira: Annotated[
        str | None,
        typer.Option("--link", help="Link to existing Jira key"),
    ] = None,
):
    """Create a new draft ticket."""
    service = _get_service()

    try:
        ticket = service.create(
            title=title,
            description=description,
            priority=priority,
            labels=labels,
            linked_jira_key=linked_jira,
        )
    except DraftTicketValidationError as exc:
        print(f"[red]Validation error:[/red] {exc}")
        raise typer.Exit(1)
    except Exception as exc:
        print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    print(f"[green]Created draft ticket:[/green] {ticket.id}")
    print(f"  Title: {ticket.suggested_title}")
    print(f"  Priority: {ticket.suggested_priority.value}")
    print(f"  Status: {ticket.status.value}")


@app.command("approve")
def approve_ticket(
    ticket_id: Annotated[str, typer.Argument(help="Draft ticket ID")],
    reviewer: Annotated[
        str | None,
        typer.Option("--reviewer", "-r", help="Name of the reviewer"),
    ] = None,
):
    """Approve a draft ticket."""
    service = _get_service()

    # Find ticket by partial ID
    tickets = service.list_all()
    matches = [t for t in tickets if t.id.startswith(ticket_id)]

    if not matches:
        print(f"[red]No ticket found matching ID: {ticket_id}[/red]")
        raise typer.Exit(1)

    if len(matches) > 1:
        print(f"[yellow]Multiple tickets match '{ticket_id}'. Please be more specific.[/yellow]")
        raise typer.Exit(1)

    try:
        ticket = service.update_status(matches[0].id, DraftTicketStatus.APPROVED, reviewed_by=reviewer)
    except DraftTicketNotFoundError as exc:
        print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    print(f"[green]Approved ticket:[/green] {ticket.id[:8]}")
    print(f"  Title: {ticket.suggested_title}")
    if ticket.reviewed_by:
        print(f"  Reviewed by: {ticket.reviewed_by}")


@app.command("reject")
def reject_ticket(
    ticket_id: Annotated[str, typer.Argument(help="Draft ticket ID")],
    reviewer: Annotated[
        str | None,
        typer.Option("--reviewer", "-r", help="Name of the reviewer"),
    ] = None,
):
    """Reject a draft ticket."""
    service = _get_service()

    # Find ticket by partial ID
    tickets = service.list_all()
    matches = [t for t in tickets if t.id.startswith(ticket_id)]

    if not matches:
        print(f"[red]No ticket found matching ID: {ticket_id}[/red]")
        raise typer.Exit(1)

    if len(matches) > 1:
        print(f"[yellow]Multiple tickets match '{ticket_id}'. Please be more specific.[/yellow]")
        raise typer.Exit(1)

    try:
        ticket = service.update_status(matches[0].id, DraftTicketStatus.REJECTED, reviewed_by=reviewer)
    except DraftTicketNotFoundError as exc:
        print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    print(f"[red]Rejected ticket:[/red] {ticket.id[:8]}")
    print(f"  Title: {ticket.suggested_title}")
    if ticket.reviewed_by:
        print(f"  Reviewed by: {ticket.reviewed_by}")


@app.command("link")
def link_ticket(
    ticket_id: Annotated[str, typer.Argument(help="Draft ticket ID")],
    jira_key: Annotated[str, typer.Option("--jira-key", "-j", help="Jira issue key (e.g., INFRA-1234)", prompt=True)],
    link_type: Annotated[
        str,
        typer.Option("--link-type", "-t", help="Link type (relates_to, blocks, subtask_of, duplicates)"),
    ] = "relates_to",
):
    """Link a draft ticket to an existing Jira issue."""
    service = _get_service()

    # Find ticket by partial ID
    tickets = service.list_all()
    matches = [t for t in tickets if t.id.startswith(ticket_id)]

    if not matches:
        print(f"[red]No ticket found matching ID: {ticket_id}[/red]")
        raise typer.Exit(1)

    if len(matches) > 1:
        print(f"[yellow]Multiple tickets match '{ticket_id}'. Please be more specific.[/yellow]")
        raise typer.Exit(1)

    try:
        ticket = service.link_to_jira(matches[0].id, jira_key=jira_key, link_type=link_type)
    except DraftTicketNotFoundError as exc:
        print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)
    except DraftTicketValidationError as exc:
        print(f"[red]Validation error:[/red] {exc}")
        raise typer.Exit(1)

    print(f"[green]Linked ticket to Jira:[/green]")
    print(f"  Ticket: {ticket.id[:8]} - {ticket.suggested_title}")
    print(f"  Jira: {ticket.linked_jira_key}")
    print(f"  Link type: {ticket.link_type.value if ticket.link_type else 'relates_to'}")
    print(f"  URL: {ticket.linked_jira_url}")


@app.command("push")
def push_ticket(
    ticket_id: Annotated[str, typer.Argument(help="Draft ticket ID")],
    jira_key: Annotated[
        str | None,
        typer.Option("--jira-key", "-j", help="Created Jira issue key (if already created manually)"),
    ] = None,
):
    """Mark a draft ticket as pushed to Jira.

    This is a placeholder - actual Jira integration would create the ticket.
    For now, provide the created Jira key if you created it manually.
    """
    service = _get_service()

    # Find ticket by partial ID
    tickets = service.list_all()
    matches = [t for t in tickets if t.id.startswith(ticket_id)]

    if not matches:
        print(f"[red]No ticket found matching ID: {ticket_id}[/red]")
        raise typer.Exit(1)

    if len(matches) > 1:
        print(f"[yellow]Multiple tickets match '{ticket_id}'. Please be more specific.[/yellow]")
        raise typer.Exit(1)

    if not jira_key:
        # In future, this would actually create the Jira ticket
        print("[yellow]Note: Actual Jira push is not yet implemented.[/yellow]")
        print("[yellow]Please create the ticket in Jira manually and provide the key with --jira-key.[/yellow]")
        raise typer.Exit(1)

    try:
        ticket = service.mark_as_pushed(matches[0].id, created_jira_key=jira_key)
    except DraftTicketNotFoundError as exc:
        print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)
    except DraftTicketValidationError as exc:
        print(f"[red]Validation error:[/red] {exc}")
        raise typer.Exit(1)

    print(f"[blue]Pushed ticket to Jira:[/blue]")
    print(f"  Ticket: {ticket.id[:8]} - {ticket.suggested_title}")
    print(f"  Created Jira: {ticket.created_jira_key}")
    print(f"  URL: {ticket.created_jira_url}")


@app.command("delete")
def delete_ticket(
    ticket_id: Annotated[str, typer.Argument(help="Draft ticket ID")],
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Skip confirmation"),
    ] = False,
):
    """Delete a draft ticket."""
    service = _get_service()

    # Find ticket by partial ID
    tickets = service.list_all()
    matches = [t for t in tickets if t.id.startswith(ticket_id)]

    if not matches:
        print(f"[red]No ticket found matching ID: {ticket_id}[/red]")
        raise typer.Exit(1)

    if len(matches) > 1:
        print(f"[yellow]Multiple tickets match '{ticket_id}'. Please be more specific.[/yellow]")
        raise typer.Exit(1)

    ticket = matches[0]

    if not force:
        confirm = typer.confirm(f"Delete ticket '{ticket.suggested_title}'?")
        if not confirm:
            print("[yellow]Cancelled.[/yellow]")
            raise typer.Abort()

    removed = service.delete(ticket.id)
    if not removed:
        print(f"[red]Failed to delete ticket: {ticket_id}[/red]")
        raise typer.Exit(1)

    print(f"[red]Deleted ticket:[/red] {ticket.id[:8]} - {ticket.suggested_title}")


@app.command("search")
def search_tickets(
    query: Annotated[str, typer.Argument(help="Search query")],
):
    """Search draft tickets by keyword."""
    service = _get_service()

    tickets = service.search(query)

    if not tickets:
        print(f"[yellow]No tickets found matching '{query}'[/yellow]")
        return

    print(f"[green]Found {len(tickets)} ticket(s) matching '{query}':[/green]\n")

    for ticket in tickets:
        status_color = _status_color(ticket.status)
        priority_color = _priority_color(ticket.suggested_priority.value)

        print(f"[bold]{ticket.id[:8]}[/bold] - {ticket.suggested_title}")
        print(
            f"  [{priority_color}]{ticket.suggested_priority.value}[/{priority_color}] | "
            f"[{status_color}]{ticket.status.value}[/{status_color}]"
        )
        if ticket.suggested_description:
            desc_preview = ticket.suggested_description[:100]
            if len(ticket.suggested_description) > 100:
                desc_preview += "..."
            print(f"  [dim]{desc_preview}[/dim]")
        print()


__all__ = ["app"]
