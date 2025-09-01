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


@export.command("devices")
def netbox_devices():
    """Export devices to CSV (incremental)."""
    require_env(["NETBOX_URL", "NETBOX_TOKEN"])
    raise_code = _run_script("netbox-export/bin/get_netbox_devices.py")
    raise SystemExit(raise_code)


@export.command("vms")
def netbox_vms():
    """Export VMs to CSV (incremental)."""
    require_env(["NETBOX_URL", "NETBOX_TOKEN"])
    raise_code = _run_script("netbox-export/bin/get_netbox_vms.py")
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
def netbox_update():
    """Run devices, vms, then merge exports in sequence."""
    require_env(["NETBOX_URL", "NETBOX_TOKEN"])  # token needed for export endpoints
    code = _run_script("netbox-export/bin/netbox_update.py")
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
