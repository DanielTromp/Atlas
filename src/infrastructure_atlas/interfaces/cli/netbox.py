"""NetBox CLI commands."""

from __future__ import annotations

import os

import typer
from rich import print

from infrastructure_atlas.env import load_env
from infrastructure_atlas.infrastructure.modules import get_module_registry

app = typer.Typer(help="NetBox helpers", context_settings={"help_option_names": ["-h", "--help"]})


@app.callback(invoke_without_command=True)
def check_module_enabled(ctx: typer.Context):
    """Ensure NetBox module is enabled before running commands."""
    if ctx.invoked_subcommand:
        registry = get_module_registry()
        try:
            registry.require_enabled("netbox")
        except Exception as e:
            print(f"[red]NetBox module is disabled:[/red] {e}")
            raise typer.Exit(code=1)


@app.command("search")
def netbox_search_cli(
    q: str = typer.Option(..., "--q", help="Full-text query"),
    dataset: str = typer.Option("all", "--dataset", help="all|devices|vms"),
    limit: int = typer.Option(50, "--limit", help="0 = no limit (fetch all pages)"),
):
    """Search NetBox live via the API (no CSV)."""
    load_env()
    from infrastructure_atlas.api.app import netbox_search as _nb

    if dataset not in ("all", "devices", "vms"):
        print("[red]dataset must be one of: all, devices, vms[/red]")
        raise SystemExit(2)
    res = _nb(dataset=dataset, q=q, limit=limit)
    from rich import print as _print

    _print({k: res.get(k) for k in ("total",)})
    for row in res.get("rows", []):
        name = row.get("Name", "")
        typ = row.get("Type", "")
        status = row.get("Status", "")
        primary = row.get("Primary IP", "")
        oob = row.get("Out-of-band IP", "")
        _print(f"- {name} [dim]({typ or 'n/a'})[/dim] — {status} — {primary or oob or '-'}")


@app.command("device-json")
def netbox_device_json(
    device_id: int = typer.Option(0, "--id", help="Device ID"),
    name: str = typer.Option("", "--name", help="Device name (exact) if --id not used"),
    raw: bool = typer.Option(False, "--raw", help="Print raw JSON only"),
):
    """Fetch full JSON for a device from NetBox and print it."""
    import requests as _rq

    load_env()
    base = os.getenv("NETBOX_URL", "").strip()
    token = os.getenv("NETBOX_TOKEN", "").strip()
    if not base or not token:
        print("[red]NETBOX_URL/NETBOX_TOKEN not configured[/red]")
        raise SystemExit(2)
    base = base.rstrip("/")
    sess = _rq.Session()
    sess.headers.update({"Authorization": f"Token {token}", "Accept": "application/json"})

    def _get(u: str):
        r = sess.get(u, timeout=30)
        r.raise_for_status()
        return r.json()

    data = None
    if device_id:
        data = _get(f"{base}/api/dcim/devices/{device_id}/")
    else:
        if not name:
            print("[red]Provide --id or --name[/red]")
            raise SystemExit(2)
        js = _get(f"{base}/api/dcim/devices/?name={name}")
        results = js.get("results", []) if isinstance(js, dict) else []
        if not results:
            print(f"[red]Not found:[/red] {name}")
            raise SystemExit(1)
        data = results[0]
    if raw:
        import json as _json

        print(_json.dumps(data, indent=2))
    else:
        from rich import print_json as _pjson

        _pjson(data=data)
