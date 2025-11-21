"""Search CLI commands - cross-system search aggregator."""

from __future__ import annotations

import json
import pathlib
import typer
from rich import print as _print
from unittest.mock import MagicMock

from infrastructure_atlas.db.models import User
from infrastructure_atlas.env import load_env
from infrastructure_atlas.infrastructure.logging import get_logger

app = typer.Typer(help="Cross-system search aggregator", context_settings={"help_option_names": ["-h", "--help"]})
logger = get_logger(__name__)


@app.command("run")
def search_run(
    q: str = typer.Option(..., "--q", "-q", help="Object name or keyword (e.g. device, vm, IP, substring)"),
    zlimit: int = typer.Option(0, "--zlimit", help="Zabbix max items (0 = no limit)"),
    jlimit: int = typer.Option(0, "--jlimit", help="Jira max issues (0 = no limit)"),
    climit: int = typer.Option(0, "--climit", help="Confluence max results (0 = no limit)"),
    vlimit: int = typer.Option(0, "--vlimit", help="vCenter max VMs (0 = no limit)"),
    json_out: bool = typer.Option(False, "--json", help="Output full JSON with all available fields"),
    out: str = typer.Option("", "--out", help="Save full JSON to file (pretty-printed)"),
):
    """Run the Search aggregator across Zabbix, Jira, Confluence, vCenter, and NetBox.

    Defaults: unlimited (zlimit/jlimit/climit/vlimit = 0). Use --json for full details.
    """
    load_env()
    logger.info(
        "Search CLI invoked",
        extra={
            "query": q,
            "zlimit": zlimit,
            "jlimit": jlimit,
            "climit": climit,
            "vlimit": vlimit,
            "json": json_out,
            "out": out or None,
        },
    )
    from infrastructure_atlas.interfaces.api.routes.search import search_aggregate as _agg
    from fastapi import Request

    # Create a mock request object for CLI usage
    mock_request = MagicMock(spec=Request)
    mock_request.state.permissions = frozenset(["vcenter.view"])  # Grant all permissions for CLI

    # Create a mock admin user for CLI
    mock_user = User(
        id="cli-user",
        username="cli",
        display_name="CLI User",
        role="admin",
        is_active=True,
    )
    mock_request.state.user = mock_user

    res = _agg(request=mock_request, q=q, zlimit=zlimit, jlimit=jlimit, climit=climit, vlimit=vlimit)
    # Save to file when requested (pretty JSON)
    if out:
        path = pathlib.Path(out)
        try:
            path.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[green]Saved:[/green] {path}")
        except Exception as e:
            print(f"[red]Failed to write {path}:[/red] {e}")
    if json_out:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return
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
        nm = it.get("Name") or ""
        typ = it.get("Type") or ""
        upd = it.get("Updated") or ""
        _print(f"  - {nm} {f'({typ})' if typ else ''} [dim]{upd}[/dim]")
    # vCenter
    v = res.get("vcenter") or {}
    _print(f"[bold]vCenter[/bold] — {v.get('total', 0)} VMs")
    for it in (v.get("items") or [])[:10]:
        vm_name = it.get("name", "")
        config_name = it.get("config_name", "")
        power_state = it.get("power_state", "")
        guest_os = it.get("guest_os", "")
        ip_addr = it.get("guest_ip_address", "")
        _print(
            f"  - {vm_name} [dim]({config_name})[/dim] {power_state} {guest_os or ''} {f'IP: {ip_addr}' if ip_addr else ''}"
        )
