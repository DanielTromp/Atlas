from __future__ import annotations

import os
import sys
import subprocess

import typer
from rich import print

from .env import load_env, project_root, require_env, apply_extra_headers, get_env


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


@export.command("devices")
def netbox_devices():
    """Export devices to CSV (incremental)."""
    require_env(["NETBOX_URL", "NETBOX_TOKEN"]) 
    raise_code = _run_script("netbox-export/bin/get_netbox_data.py")
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
    import pynetbox

    require_env(["NETBOX_URL"])  # token may be optional for /api/status/
    url = os.getenv("NETBOX_URL", "").rstrip("/")
    token = os.getenv("NETBOX_TOKEN", "")

    nb = pynetbox.api(url, token=token if token else None)
    apply_extra_headers(nb.http_session)

    status_url = f"{url}/api/status/"
    devices_url = f"{url}/api/dcim/devices/?limit=1"

    print(f"[bold]Base:[/bold] {url}")
    if token:
        print(f"[bold]Auth:[/bold] Token present (len={len(token)})")
    else:
        print("[bold]Auth:[/bold] No token set")

    try:
        r = nb.http_session.get(status_url, timeout=15)
        print(f"[bold]/api/status/:[/bold] HTTP {r.status_code}")
        ctype = r.headers.get("content-type", "")
        if "json" in ctype:
            try:
                data = r.json()
                # Print a compact summary
                keys = ", ".join(list(data.keys())[:8])
                print(f"  JSON keys: {keys}")
                version = data.get("netbox-version") or data.get("version")
                if version:
                    print(f"  Version: {version}")
            except Exception:
                pass
        else:
            snippet = (r.text or "").strip().splitlines()[0:1]
            if snippet:
                print(f"  Response snippet: {snippet[0][:120]}")
    except Exception as e:
        print(f"Error requesting /api/status/: {e}")

    # Token/access probe
    try:
        r2 = nb.http_session.get(devices_url, timeout=15)
        print(f"[bold]/api/dcim/devices/:[/bold] HTTP {r2.status_code}")
        if r2.status_code == 403:
            print("  403 Forbidden: check API token permissions or WAF/Access requirements.")
            snippet = (r2.text or "").strip().replace("\n", " ")
            if snippet:
                print(f"  Response snippet: {snippet[:200]}")
        elif r2.status_code == 200 and "json" in r2.headers.get("content-type", ""):
            try:
                data = r2.json()
                count_hint = data.get("count")
                if count_hint is not None:
                    print(f"  Result: count={count_hint}")
            except Exception:
                pass
        else:
            snippet = (r2.text or "").strip().replace("\n", " ")
            if snippet:
                print(f"  Response snippet: {snippet[:200]}")
    except Exception as e:
        print(f"Error requesting devices: {e}")


@export.command("update")
def netbox_update():
    """Run devices, vms, then merge exports in sequence."""
    require_env(["NETBOX_URL", "NETBOX_TOKEN"])  # token needed for export endpoints
    steps = [
        ("devices", "netbox-export/bin/get_netbox_data.py"),
        ("vms", "netbox-export/bin/get_netbox_vms.py"),
        ("merge", "netbox-export/bin/merge_netbox_csvs.py"),
    ]
    for name, rel in steps:
        print(f"[bold]Running {name}...[/bold]")
        code = _run_script(rel)
        if code != 0:
            print(f"[red]Step failed:[/red] {name} (exit {code})")
            raise SystemExit(code)
    print("[green]Update complete: devices + vms + merge[/green]")

    # Auto-publish CMDB to SharePoint when configured
    try:
        site_url = os.getenv("SPO_SITE_URL", "").strip()
        has_user = bool(os.getenv("SPO_USERNAME")) and bool(os.getenv("SPO_PASSWORD"))
        has_app = all(bool(os.getenv(k)) for k in ["SPO_TENANT_ID", "SPO_CLIENT_ID", "SPO_CLIENT_SECRET"])
        if site_url and (has_user or has_app):
            print("[bold]Publishing CMDB to SharePoint...[/bold]")
            auth_mode = "userpass" if has_user else "app"
            sharepoint_publish_cmdb(auth=auth_mode, replace=True)
        else:
            print("[dim]SharePoint not configured; skipping auto publish[/dim]")
    except Exception as e:
        print(f"[red]SharePoint publish failed:[/red] {e}")


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
    """Upload a file to a SharePoint Site's default drive via Microsoft Graph."""
    # Common
    import os
    from urllib.parse import urlparse
    from office365.runtime.client_request_exception import ClientRequestException

    site_url = get_env("SPO_SITE_URL", required=True)  # e.g. https://voiceworks0.sharepoint.com/sites/portal/circles/sas
    # Handle URL source download
    import tempfile, shutil
    src = os.fspath(file)
    tmp_path = None
    if src.lower().startswith(("http://", "https://")):
        try:
            import requests
        except Exception:
            print("[red]Missing dependency 'requests' to download URLs[/red]")
            raise SystemExit(1)
        print(f"[bold]Downloading:[/bold] {src}")
        r = requests.get(src, stream=True, timeout=60)
        r.raise_for_status()
        url_name = os.path.basename(urlparse(src).path) or "download.bin"
        fd, tmp_path = tempfile.mkstemp(prefix="spul_", suffix="_" + url_name)
        with os.fdopen(fd, "wb") as fh:
            for chunk in r.iter_content(chunk_size=64 * 1024):
                if chunk:
                    fh.write(chunk)
        src = tmp_path
    if not os.path.exists(src):
        print(f"[red]File not found:[/red] {src}")
        raise SystemExit(1)
    # Derive destination dir and filename
    raw_dest = (dest_path or os.getenv("SPO_DEST_PATH", "")).strip().strip("/")
    dest_dir = raw_dest
    dest_name = None
    if raw_dest:
        parts = [p for p in raw_dest.split("/") if p]
        if len(parts) >= 1 and "." in parts[-1]:
            dest_name = parts[-1]
            dest_dir = "/".join(parts[:-1])
    fname = dest_name or os.path.basename(src)

    # Determine auth mode
    auth = (auth or "auto").lower()
    has_app = all(bool(os.getenv(k)) for k in ["SPO_TENANT_ID", "SPO_CLIENT_ID", "SPO_CLIENT_SECRET"])
    has_user = all(bool(os.getenv(k)) for k in ["SPO_USERNAME", "SPO_PASSWORD"])
    mode = "app" if (auth == "app" or (auth == "auto" and has_app and not has_user)) else ("userpass" if (auth == "userpass" or (auth == "auto" and has_user)) else None)
    if not mode:
        print("[red]No valid auth configured[/red]. Set either app creds (SPO_TENANT_ID, SPO_CLIENT_ID, SPO_CLIENT_SECRET) or user creds (SPO_USERNAME, SPO_PASSWORD), or pass --auth app|userpass.")
        raise SystemExit(1)

    print(f"[bold]Site:[/bold] {site_url}")
    print(f"[bold]Mode:[/bold] {mode}")

    if mode == "app":
        # Microsoft Graph app‑only flow (sites drive)
        import msal
        from office365.graph_client import GraphClient

        tenant_id = get_env("SPO_TENANT_ID", required=True)
        client_id = get_env("SPO_CLIENT_ID", required=True)
        client_secret = get_env("SPO_CLIENT_SECRET", required=True)

        authority = f"https://login.microsoftonline.com/{tenant_id}"
        app_msal = msal.ConfidentialClientApplication(
            client_id=client_id,
            authority=authority,
            client_credential=client_secret,
        )

        def acquire_token():
            token = app_msal.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
            if not token or "access_token" not in token:
                raise RuntimeError(f"Failed to acquire token: {token}")
            return token

        client = GraphClient(acquire_token)
        site = client.sites.get_by_url(site_url).get().execute_query()
        drive = site.drive.get().execute_query()
        root = drive.root.get().execute_query()  # DriveItem

        # Folder resolution
        target = root
        if dest_dir:
            target = root.get_by_path(dest_dir).get().execute_query()
            print(f"[bold]Destination:[/bold] /{dest_dir}")
        else:
            print("[bold]Destination:[/bold] drive root")

        print(f"[bold]Uploading:[/bold] {src} -> {fname}")
        if not replace:
            try:
                existing = target.children[fname].get().execute_query()
                if existing and existing.properties.get("id"):
                    print(f"[red]Exists:[/red] {fname} (use --replace to overwrite)")
                    raise SystemExit(2)
            except ClientRequestException as ex:
                if ex.response.status_code != 404:
                    raise
        size = os.path.getsize(src)
        if size <= 4 * 1024 * 1024 and dest_name is not None:
            with open(src, "rb") as fh:
                target.upload(fname, fh.read()).execute_query()
        elif size <= 4 * 1024 * 1024:
            target.upload_file(src).execute_query()
        else:
            use_path = src
            if dest_name is not None and os.path.basename(src) != dest_name:
                tmp_dir = tempfile.mkdtemp(prefix="spul_rename_")
                use_path = os.path.join(tmp_dir, fname)
                shutil.copyfile(src, use_path)
            target.resumable_upload(use_path).execute_query()
        print("[green]Upload complete[/green]")
        # Print a stable open link if available
        try:
            new_item = target.children[fname].get().execute_query()
            web_url = getattr(new_item, "web_url", None) or new_item.properties.get("webUrl")
            if web_url:
                print(f"[bold]Open (web):[/bold] {web_url}")
        except Exception:
            pass
        return

    # mode == userpass: SharePoint CSOM with service account
    from office365.sharepoint.client_context import ClientContext
    from office365.runtime.auth.user_credential import UserCredential
    from office365.sharepoint.files.file import File
    from uuid import uuid4
    from datetime import datetime
    import time
    from urllib.parse import quote

    username = get_env("SPO_USERNAME", required=True)
    password = get_env("SPO_PASSWORD", required=True)

    ctx = ClientContext(site_url).with_credentials(UserCredential(username, password))

    # Resolve server-relative site path
    site_rel = urlparse(site_url).path.rstrip("/")
    if not site_rel:
        site_rel = "/"
    # Try configured or default library names
    from urllib.parse import unquote
    preferred = os.getenv("SPO_DOC_LIB", "").strip()
    preferred_clean = unquote(preferred) if preferred else ""
    candidates = [preferred_clean] if preferred_clean else ["Shared Documents", "Documents"]
    lib_folder = None
    last_error = None
    for doclib in candidates:
        base = f"{site_rel}/{doclib}" if site_rel != "/" else f"/{doclib}"
        try:
            lib_folder = ctx.web.get_folder_by_server_relative_url(base).get().execute_query()
            print(f"[bold]Library:[/bold] {doclib}")
            break
        except ClientRequestException as ex:
            last_error = ex
            continue
    if lib_folder is None:
        msg = f"Could not find default document library under {site_rel}. Tried: {', '.join(candidates)}"
        if last_error is not None:
            msg += f" (last error HTTP {getattr(last_error.response, 'status_code', '?')})"
        print(f"[red]{msg}[/red]")
        raise SystemExit(1)

    # Navigate/create destination path using ensure_folder_path for robustness
    from requests import HTTPError as RequestsHTTPError
    if dest_dir:
        print(f"[bold]Destination:[/bold] /{dest_dir}")
        # Normalize if user included the library name in --dest (strip it)
        lib_name = getattr(lib_folder, 'name', None) or candidates[0]
        parts = [p for p in dest_dir.split('/') if p]
        if parts:
            first = unquote(parts[0])
            if first.lower() == unquote(lib_name).lower():
                dest_dir = '/'.join(parts[1:])
        # ensure_folder_path expects a web-relative path like "<Library>/foo/bar"
        rel_path = f"{lib_name}/{dest_dir}" if dest_dir else str(lib_name)
        try:
            target = ctx.web.ensure_folder_path(rel_path).execute_query()
            target = getattr(target, "value", target)  # ClientResult -> Folder
            if not getattr(target, "serverRelativeUrl", None):
                sr = f"{site_rel}/{rel_path}" if site_rel != "/" else f"/{rel_path}"
                target = ctx.web.get_folder_by_server_relative_url(sr).get().execute_query()
        except Exception:
            # Fallback per-segment creation
            target = lib_folder
            for segment in [p for p in dest_dir.split("/") if p]:
                sr = f"{target.serverRelativeUrl}/{segment}" if getattr(target, "serverRelativeUrl", "/") != "/" else f"/{segment}"
                try:
                    target = ctx.web.get_folder_by_server_relative_url(sr).get().execute_query()
                except Exception:
                    target = target.folders.add(segment).execute_query()
    else:
        print("[bold]Destination:[/bold] library root")
        target = lib_folder

    # Replace handling
    if not replace:
        try:
            existing = target.files.get_by_url(fname).get().execute_query()
            if existing and existing.properties.get("UniqueId"):
                print(f"[red]Exists:[/red] {fname} (use --replace to overwrite)")
                raise SystemExit(2)
        except ClientRequestException as ex:
            if ex.response.status_code != 404:
                raise

    # Upload (small or chunked)
    size = os.path.getsize(src)
    print(f"[bold]Uploading:[/bold] {src} ({size} bytes) -> {fname}")
    def _do_upload():
        if size <= 4 * 1024 * 1024:
            with open(src, "rb") as fh:
                return target.upload_file(fname, fh.read()).execute_query()
        else:
            # Create or overwrite empty file, then chunked upload
            target.files.add(fname, b"", True).execute_query()
            upload_id = str(uuid4())
            chunk_size = 5 * 1024 * 1024
            sent = 0
            with open(src, "rb") as fh:
                # first chunk
                chunk = fh.read(chunk_size)
                result = target.files.get_by_url(fname).start_upload(upload_id, chunk).execute_query()
                sent = int(result.value)
                while sent + chunk_size < size:
                    chunk = fh.read(chunk_size)
                    result = target.files.get_by_url(fname).continue_upload(upload_id, sent, chunk).execute_query()
                    sent = int(result.value)
                # last chunk
                last = fh.read(size - sent)
                target.files.get_by_url(fname).finish_upload(upload_id, sent, last).execute_query()

    try:
        _do_upload()
    except ClientRequestException as ex:
        msg = str(ex)
        code = getattr(getattr(ex, 'response', None), 'status_code', None)
        if force and (code == 423 or 'SPFileLockException' in msg or 'Locked' in msg):
            print("[yellow]File is locked; attempting forced update (checkout -> save -> checkin).[/yellow]")
            try:
                sp_file = target.files.get_by_url(fname).get().execute_query()
            except Exception:
                sp_file = None
            # Try checkout (ignore errors)
            try:
                if sp_file is not None:
                    sp_file.checkout().execute_query()
            except Exception:
                pass
            # Try save_binary_stream directly on the existing file
            try:
                with open(src, 'rb') as fh:
                    if sp_file is None:
                        sp_file = target.files.get_by_url(fname)
                    sp_file.save_binary_stream(fh.read()).execute_query()
            except Exception as e2:
                print(f"[red]Forced save failed:[/red] {e2}")
                # As a last resort, upload with a timestamped filename to avoid lock
                ts = datetime.now().strftime("%Y%m%d-%H%M%S")
                base, ext = os.path.splitext(fname)
                alt_name = f"{base} {ts}{ext or ''}"
                print(f"[yellow]Uploading with alternate name due to lock:[/yellow] {alt_name}")
                with open(src, 'rb') as fh:
                    target.upload_file(alt_name, fh.read()).execute_query()
                print("[green]Alternate upload complete[/green]")
                # Exit early after alternate upload
                print("[yellow]Original file remained locked; uploaded new copy instead.[/yellow]")
                print("[yellow]Consider closing the file in Office/Teams/OneDrive to allow replacement next run.[/yellow]")
                return
            # Try checkin (ignore errors)
            try:
                sp_file.checkin("Auto update", 1).execute_query()
            except Exception:
                pass
            print("[green]Forced update complete[/green]")
        else:
            raise

    print("[green]Upload complete[/green]")
    # Print Doc.aspx (sourcedoc) link, direct web link, and short viewer link
    try:
        sp_file = target.files.get_by_url(fname).get().select(["UniqueId", "ServerRelativeUrl"]).execute_query()
        guid = sp_file.properties.get("UniqueId")
        if guid:
            doc = f"{site_url.rstrip('/')}/_layouts/15/Doc.aspx?sourcedoc=%7B{guid}%7D&file={quote(fname)}&action=default&mobileredirect=true"
            print(f"[bold]Open (Doc.aspx):[/bold] {doc}")
            # Short viewer link format: /:x:/r/<path>?d=w<guid_nodash_lower>&csf=1&web=1&isSPOFile=1
            try:
                from urllib.parse import quote as urlquote
                g_nodash = guid.replace("-", "").lower().strip("{}")
                origin = f"{urlparse(site_url).scheme}://{urlparse(site_url).netloc}"
                rel = sp_file.properties.get("ServerRelativeUrl")
                # Ensure we use /r/ path with encoded components
                short_path = "/:x:/r" + "/" + "/".join([p for p in rel.split("/") if p])
                short = f"{origin}{short_path}?d=w{g_nodash}&csf=1&web=1&isSPOFile=1"
                print(f"[bold]Open (short):[/bold] {short}")
            except Exception:
                pass
        try:
            origin = f"{urlparse(site_url).scheme}://{urlparse(site_url).netloc}"
            sr_path = sp_file.properties.get("ServerRelativeUrl") or f"{lib_folder.serverRelativeUrl}/{fname}"
            web = f"{origin}{sr_path}?web=1"
            print(f"[bold]Open (web):[/bold] {web}")
        except Exception:
            pass
    except Exception:
        pass
    # Cleanup temp file
    if tmp_path and os.path.exists(tmp_path):
        try:
            os.remove(tmp_path)
        except Exception:
            pass


def main():  # entry point for console_scripts
    app()


@sharepoint.command("publish-cmdb")
def sharepoint_publish_cmdb(
    auth: str = typer.Option("userpass", "--auth", help="Auth mode: userpass|app"),
    replace: bool = typer.Option(True, "--replace/--no-replace", help="Replace if exists"),
):
    """Publish the standard NetBox CMDB Excel to SharePoint.

    Equivalent to:
    netbox sharepoint upload --auth userpass \
      --file "netbox-export/data/Systems CMDB.xlsx" \
      --dest "Important Info/Autosync/Systems CMDB.xlsx"
    """
    sharepoint_upload(
        file="netbox-export/data/Systems CMDB.xlsx",
        dest_path="Important Info/Autosync/Systems CMDB.xlsx",
        replace=replace,
        auth=auth,
        force=True,
    )
