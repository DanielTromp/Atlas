from __future__ import annotations

import os
import subprocess
import sys

import typer
from rich import print

from .env import load_env, project_root, require_env

app = typer.Typer(help="NetBox CLI")


def _run_script(relpath: str, *args: str) -> int:
    """Run a Python script at repo-relative path with inherited env."""
    root = project_root()
    script = root / relpath
    if not script.exists():
        print(f"[red]Script not found:[/red] {script}")
        return 1
    cmd = [sys.executable, str(script), *args]
    return subprocess.call(cmd, cwd=root, env=os.environ.copy())


@app.callback()
def _common(override_env: bool = typer.Option(False, "--override-env", help="Override existing env vars from .env")):
    env_path = load_env(override=override_env)
    print(f"[dim]Using .env: {env_path}[/dim]")


export = typer.Typer(help="Export helpers")
app.add_typer(export, name="export")
sharepoint = typer.Typer(help="SharePoint helpers")
app.add_typer(sharepoint, name="sharepoint")
api = typer.Typer(help="API server")
app.add_typer(api, name="api")
zabbix = typer.Typer(help="Zabbix helpers")
app.add_typer(zabbix, name="zabbix")


@export.command("devices")
def netbox_devices(
    force: bool = typer.Option(False, "--force", help="Re-fetch all devices and rewrite CSV"),
):
    """Export devices to CSV (incremental)."""
    require_env(["NETBOX_URL", "NETBOX_TOKEN"])
    args = ["--force"] if force else []
    raise_code = _run_script("netbox-export/bin/get_netbox_devices.py", *args)
    raise SystemExit(raise_code)


@export.command("vms")
def netbox_vms(
    force: bool = typer.Option(False, "--force", help="Re-fetch all VMs and rewrite CSV"),
):
    """Export VMs to CSV (incremental)."""
    require_env(["NETBOX_URL", "NETBOX_TOKEN"])
    args = ["--force"] if force else []
    raise_code = _run_script("netbox-export/bin/get_netbox_vms.py", *args)
    raise SystemExit(raise_code)


@export.command("merge")
def netbox_merge():
    """Merge devices+vms CSV into a single CSV and Excel."""
    raise_code = _run_script("netbox-export/bin/merge_netbox_csvs.py")
    raise SystemExit(raise_code)


@app.command("status")
def netbox_status():
    """Check API status and token access (200/403 details)."""
    code = _run_script("netbox-export/bin/netbox_status.py")
    raise SystemExit(code)


@export.command("update")
def netbox_update(
    force: bool = typer.Option(False, "--force", help="Re-fetch all devices and VMs before merge"),
):
    """Run devices, vms, then merge exports in sequence."""
    require_env(["NETBOX_URL", "NETBOX_TOKEN"])  # token needed for export endpoints
    args = ["--force"] if force else []
    code = _run_script("netbox-export/bin/netbox_update.py", *args)
    if code != 0:
        raise SystemExit(code)

    # Auto-publish CMDB to SharePoint when configured
    try:
        site_url = os.getenv("SPO_SITE_URL", "").strip()
        has_user = bool(os.getenv("SPO_USERNAME")) and bool(os.getenv("SPO_PASSWORD"))
        has_app = all(bool(os.getenv(k)) for k in ["SPO_TENANT_ID", "SPO_CLIENT_ID", "SPO_CLIENT_SECRET"])
        if site_url and (has_user or has_app):
            print("[bold]Publishing CMDB to SharePoint...[/bold]")
            auth_mode = "userpass" if has_user else "app"
            _ = _run_script("netbox-export/bin/sharepoint_publish_cmdb.py", "--auth", auth_mode, "--replace")
        else:
            print("[dim]SharePoint not configured; skipping auto publish[/dim]")
    except Exception as e:
        print(f"[red]SharePoint publish failed:[/red] {e}")


@api.command("serve")
def api_serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host"),
    port: int = typer.Option(8000, "--port", help="Bind port"),
    reload: bool = typer.Option(True, "--reload/--no-reload", help="Auto-reload on changes"),
):
    """Run the FastAPI server (serves CSV data via DuckDB)."""
    import uvicorn

    # ASGI app path: src/enreach_tools/api/app.py -> app
    uvicorn.run("enreach_tools.api.app:app", host=host, port=port, reload=reload)


@zabbix.command("problems")
def zabbix_problems_cli(
    limit: int = typer.Option(20, "--limit", help="Max items"),
    severities: str = typer.Option("", "--severities", help="Comma list, e.g. 2,3,4 (defaults from .env)"),
    groupids: str = typer.Option("", "--groupids", help="Comma list group IDs (default from .env)"),
    all: bool = typer.Option(False, "--all", help="Include acknowledged (unacknowledged=0)"),
):
    """Fetch problems from Zabbix via JSON-RPC and print a summary."""
    import requests as _rq
    from rich import print as _print
    from .env import load_env as _load

    _load()
    base = os.getenv("ZABBIX_API_URL", "").strip() or os.getenv("ZABBIX_HOST", "").strip()
    if not base:
        _print("[red]ZABBIX_API_URL or ZABBIX_HOST not set[/red]")
        raise SystemExit(1)
    if not base.endswith("/api_jsonrpc.php"):
        base = base.rstrip("/") + "/api_jsonrpc.php"
    token = os.getenv("ZABBIX_API_TOKEN", "").strip()
    if not token:
        _print("[yellow]Warning:[/yellow] ZABBIX_API_TOKEN not set; request may be unauthorized")

    def _rpc(method: str, params: dict) -> dict:
        body = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
        if token:
            body["auth"] = token
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        r = _rq.post(base, headers=headers, json=body, timeout=30)
        r.raise_for_status()
        data = r.json()
        if data.get("error"):
            raise RuntimeError(f"Zabbix error: {data['error']}")
        return data.get("result", {})

    # Params
    sev_list = []
    if severities.strip():
        try:
            sev_list = [int(x) for x in severities.split(",") if x.strip()]
        except Exception:
            pass
    elif os.getenv("ZABBIX_SEVERITIES", "").strip():
        try:
            sev_list = [int(x) for x in os.getenv("ZABBIX_SEVERITIES").split(",") if x.strip()]
        except Exception:
            pass
    grp_list = []
    if groupids.strip():
        try:
            grp_list = [int(x) for x in groupids.split(",") if x.strip()]
        except Exception:
            pass
    elif os.getenv("ZABBIX_GROUP_ID", "").strip().isdigit():
        grp_list = [int(os.getenv("ZABBIX_GROUP_ID").strip())]

    params = {
        "output": ["eventid", "name", "severity", "clock", "acknowledged", "r_eventid", "source", "object", "objectid"],
        "selectTags": "extend",
        "recent": True,
        "limit": int(limit),
    }
    if sev_list:
        params["severities"] = sev_list
    if grp_list:
        params["groupids"] = grp_list
    # Default: show only unacknowledged; when --all, remove filter to show both
    if not all:
        params["acknowledged"] = 0

    try:
        res = _rpc("problem.get", params)
    except Exception as ex:
        _print(f"[red]Request failed:[/red] {ex}")
        raise SystemExit(1)

    items = res if isinstance(res, list) else []
    items.sort(key=lambda x: int(x.get("clock") or 0), reverse=True)
    _print(f"[bold]Problems:[/bold] {len(items)} (showing up to {limit})")
    from datetime import datetime as _dt
    for it in items[: limit]:
        clk = int(it.get("clock") or 0)
        ts = _dt.utcfromtimestamp(clk).strftime("%Y-%m-%d %H:%M:%S") if clk else "?"
        sev = int(it.get("severity") or 0)
        name = it.get("name") or ""
        _print(f"- [{ts}] sev={sev} {name}")


@sharepoint.command("upload")
def sharepoint_upload(
    file: str = typer.Option(
        "netbox-export/data/Systems CMDB.xlsx",
        "--file",
        help="Local file or http(s) URL to upload",
    ),
    dest_path: str = typer.Option(
        "",
        "--dest",
        help="Drive-relative folder path (e.g. 'Reports/CMDB')",
    ),
    replace: bool = typer.Option(True, "--replace/--no-replace", help="Replace if exists"),
    auth: str = typer.Option(
        "auto",
        "--auth",
        help="Auth mode: auto|app|userpass",
    ),
    force: bool = typer.Option(True, "--force/--no-force", help="Force overwrite if file is locked (423)"),
):
    """Upload a file to a SharePoint Site's default drive via Microsoft Graph or CSOM (delegated)."""
    args = [
        "--file",
        file,
        "--auth",
        auth,
    ]
    if dest_path:
        args += ["--dest", dest_path]
    args.append("--replace" if replace else "--no-replace")
    args.append("--force" if force else "--no-force")
    code = _run_script("netbox-export/bin/sharepoint_upload.py", *args)
    raise SystemExit(code)


def main():  # entry point for console_scripts
    app()


@sharepoint.command("publish-cmdb")
def sharepoint_publish_cmdb(
    auth: str = typer.Option("userpass", "--auth", help="Auth mode: userpass|app"),
    replace: bool = typer.Option(True, "--replace/--no-replace", help="Replace if exists"),
):
    """Publish the standard NetBox CMDB Excel to SharePoint."""
    args = [
        "--auth",
        auth,
    ]
    args.append("--replace" if replace else "--no-replace")
    code = _run_script("netbox-export/bin/sharepoint_publish_cmdb.py", *args)
    raise SystemExit(code)
