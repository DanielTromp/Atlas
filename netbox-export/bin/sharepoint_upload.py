#!/usr/bin/env python3
import argparse
import os
import sys
import tempfile
from urllib.parse import quote, unquote, urlparse
from uuid import uuid4

from rich import print

from enreach_tools.env import get_env, load_env


def download_if_url(src: str) -> str:
    if not src.lower().startswith(("http://", "https://")):
        return src
    try:
        import requests
    except Exception:
        print("[red]Missing dependency 'requests' to download URLs[/red]")
        raise SystemExit(1) from None
    print(f"[bold]Downloading:[/bold] {src}")
    r = requests.get(src, stream=True, timeout=60)
    r.raise_for_status()
    url_name = os.path.basename(urlparse(src).path) or "download.bin"
    fd, tmp_path = tempfile.mkstemp(prefix="spul_", suffix="_" + url_name)
    with os.fdopen(fd, "wb") as fh:
        for chunk in r.iter_content(chunk_size=64 * 1024):
            if chunk:
                fh.write(chunk)
    return tmp_path


def upload_app_mode(site_url: str, src: str, dest_dir: str, fname: str, replace: bool):
    import msal
    from office365.graph_client import GraphClient
    from office365.runtime.client_request_exception import ClientRequestException

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
    root = drive.root.get().execute_query()

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
    if size <= 4 * 1024 * 1024 and "." in fname:
        with open(src, "rb") as fh:
            target.upload(fname, fh.read()).execute_query()
    elif size <= 4 * 1024 * 1024:
        target.upload_file(src).execute_query()
    else:
        target.resumable_upload(src).execute_query()
    print("[green]Upload complete[/green]")

    # Stable open link
    try:
        new_item = target.children[fname].get().execute_query()
        web_url = getattr(new_item, "web_url", None) or new_item.properties.get("webUrl")
        if web_url:
            print(f"[bold]Open (web):[/bold] {web_url}")
    except Exception:
        pass


def upload_userpass_mode(site_url: str, src: str, dest_dir: str, fname: str, replace: bool, force: bool):
    from datetime import datetime

    from urllib.parse import urlparse as _urlparse

    from office365.runtime.auth.user_credential import UserCredential
    from office365.runtime.client_request_exception import ClientRequestException
    from office365.sharepoint.client_context import ClientContext

    username = get_env("SPO_USERNAME", required=True)
    password = get_env("SPO_PASSWORD", required=True)

    # Establish CSOM context with user/pass credentials
    try:
        ctx = ClientContext(site_url).with_credentials(UserCredential(username, password))
    except Exception as auth_exc:  # Authentication or cookie bootstrap failed
        msg = str(auth_exc)
        host = _urlparse(site_url).netloc
        hints: list[str] = []

        # Cross-tenant/guest indicator: username domain and site tenant differ
        upn_domain = username.split("@", 1)[-1] if "@" in username else ""
        if upn_domain and upn_domain.lower() not in host.lower():
            hints.append(
                "Account domain differs from tenant; user/pass CSOM may not work for guest/B2B users."
            )

        # Common conditional access / MFA cases
        hints.extend([
            "Verify the service account can sign into the site in a browser without extra prompts (no MFA/consent).",
            "Ensure the password is correct and not expired/locked (try changing it and re-run).",
            "Check tenant Conditional Access; programmatic legacy cookie auth can be blocked.",
            "If possible, prefer app-only auth (SPO_TENANT_ID/CLIENT_ID/CLIENT_SECRET).",
        ])

        print(
            "[red]User/pass authentication failed[/red]: "
            + ("auth cookies error; " if "wsignin1.0" in msg or "auth cookies" in msg.lower() else "")
            + f"{msg}"
        )
        print("[bold]Site:[/bold] " + site_url)
        print("[bold]User:[/bold] " + username)
        for h in hints:
            print("[dim]- " + h + "[/dim]")
        raise SystemExit(1)

    # Resolve server-relative site path
    site_rel = urlparse(site_url).path.rstrip("/") or "/"
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

    # Navigate/create destination path
    if dest_dir:
        print(f"[bold]Destination:[/bold] /{dest_dir}")
        from urllib.parse import unquote as _unquote
        lib_name = getattr(lib_folder, "name", None) or candidates[0]
        parts = [p for p in dest_dir.split("/") if p]
        if parts:
            first = _unquote(parts[0])
            if first.lower() == _unquote(lib_name).lower():
                dest_dir = "/".join(parts[1:])
        rel_path = f"{lib_name}/{dest_dir}" if dest_dir else str(lib_name)
        try:
            target = ctx.web.ensure_folder_path(rel_path).execute_query()
            target = getattr(target, "value", target)
            if not getattr(target, "serverRelativeUrl", None):
                sr = f"{site_rel}/{rel_path}" if site_rel != "/" else f"/{rel_path}"
                target = ctx.web.get_folder_by_server_relative_url(sr).get().execute_query()
        except Exception:
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

    if not replace:
        try:
            existing = target.files.get_by_url(fname).get().execute_query()
            if existing and existing.properties.get("UniqueId"):
                print(f"[red]Exists:[/red] {fname} (use --replace to overwrite)")
                raise SystemExit(2)
        except ClientRequestException as ex:
            if ex.response.status_code != 404:
                raise

    size = os.path.getsize(src)
    print(f"[bold]Uploading:[/bold] {src} ({size} bytes) -> {fname}")

    def _do_upload():
        if size <= 4 * 1024 * 1024:
            with open(src, "rb") as fh:
                return target.upload_file(fname, fh.read()).execute_query()
        else:
            target.files.add(fname, b"", True).execute_query()
            upload_id = str(uuid4())
            chunk_size = 5 * 1024 * 1024
            sent = 0
            with open(src, "rb") as fh:
                chunk = fh.read(chunk_size)
                result = target.files.get_by_url(fname).start_upload(upload_id, chunk).execute_query()
                sent = int(result.value)
                while sent + chunk_size < size:
                    chunk = fh.read(chunk_size)
                    result = target.files.get_by_url(fname).continue_upload(upload_id, sent, chunk).execute_query()
                    sent = int(result.value)
                last = fh.read(size - sent)
                target.files.get_by_url(fname).finish_upload(upload_id, sent, last).execute_query()

    from office365.runtime.client_request_exception import ClientRequestException
    try:
        _do_upload()
    except ClientRequestException as ex:
        msg = str(ex)
        code = getattr(getattr(ex, "response", None), "status_code", None)
        if force and (code == 423 or "SPFileLockException" in msg or "Locked" in msg):
            print("[yellow]File is locked; attempting forced update (checkout -> save -> checkin).[/yellow]")
            try:
                sp_file = target.files.get_by_url(fname).get().execute_query()
            except Exception:
                sp_file = None
            try:
                if sp_file is not None:
                    sp_file.checkout().execute_query()
            except Exception:
                pass
            try:
                with open(src, "rb") as fh:
                    if sp_file is None:
                        sp_file = target.files.get_by_url(fname)
                    sp_file.save_binary_stream(fh.read()).execute_query()
            except Exception as e2:
                print(f"[red]Forced save failed:[/red] {e2}")
                ts = datetime.now().strftime("%Y%m%d-%H%M%S")
                base, ext = os.path.splitext(fname)
                alt_name = f"{base} {ts}{ext or ''}"
                print(f"[yellow]Uploading with alternate name due to lock:[/yellow] {alt_name}")
                with open(src, "rb") as fh:
                    target.upload_file(alt_name, fh.read()).execute_query()
                print("[green]Alternate upload complete[/green]")
                print("[yellow]Original file remained locked; uploaded new copy instead.[/yellow]")
                print("[yellow]Consider closing the file in Office/Teams/OneDrive to allow replacement next run.[/yellow]")
                return
            try:
                sp_file.checkin("Auto update", 1).execute_query()
            except Exception:
                pass
            print("[green]Forced update complete[/green]")
        else:
            raise

    print("[green]Upload complete[/green]")
    # Print Doc.aspx, short link, direct link
    try:
        sp_file = target.files.get_by_url(fname).get().select(["UniqueId", "ServerRelativeUrl"]).execute_query()
        guid = sp_file.properties.get("UniqueId")
        if guid:
            doc = f"{site_url.rstrip('/')}/_layouts/15/Doc.aspx?sourcedoc=%7B{guid}%7D&file={quote(fname)}&action=default&mobileredirect=true"
            print(f"[bold]Open (Doc.aspx):[/bold] {doc}")
            try:
                g_nodash = guid.replace("-", "").lower().strip("{}")
                origin = f"{urlparse(site_url).scheme}://{urlparse(site_url).netloc}"
                rel = sp_file.properties.get("ServerRelativeUrl")
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


def main() -> int:
    load_env()
    parser = argparse.ArgumentParser(description="Upload a file to SharePoint via Graph or CSOM")
    parser.add_argument("--file", dest="file", default="netbox-export/data/Systems CMDB.xlsx",
                        help="Local file path or http(s) URL")
    parser.add_argument("--dest", dest="dest_path", default="",
                        help="Drive-relative folder path (e.g. 'Reports/CMDB') or include filename")
    parser.add_argument("--auth", dest="auth", default="auto", choices=["auto", "app", "userpass"],
                        help="Auth mode: auto|app|userpass")
    parser.add_argument("--replace", dest="replace", action="store_true", default=True,
                        help="Replace if exists (default)")
    parser.add_argument("--no-replace", dest="replace", action="store_false",
                        help="Do not replace if exists")
    parser.add_argument("--force", dest="force", action="store_true", default=True,
                        help="Force overwrite if file is locked (default)")
    parser.add_argument("--no-force", dest="force", action="store_false",
                        help="Do not force overwrite when locked")

    args = parser.parse_args()

    site_url = get_env("SPO_SITE_URL", required=True)

    # Handle URL source download
    src = os.fspath(args.file)
    tmp_path = None
    if src.lower().startswith(("http://", "https://")):
        tmp_path = download_if_url(src)
        src = tmp_path
    if not os.path.exists(src):
        print(f"[red]File not found:[/red] {src}")
        return 1

    # Derive destination dir and filename
    raw_dest = (args.dest_path or os.getenv("SPO_DEST_PATH", "")).strip().strip("/")
    dest_dir = raw_dest
    dest_name = None
    if raw_dest:
        parts = [p for p in raw_dest.split("/") if p]
        if len(parts) >= 1 and "." in parts[-1]:
            dest_name = parts[-1]
            dest_dir = "/".join(parts[:-1])
    fname = dest_name or os.path.basename(src)

    # Determine auth mode
    auth = (args.auth or "auto").lower()
    has_app = all(bool(os.getenv(k)) for k in ["SPO_TENANT_ID", "SPO_CLIENT_ID", "SPO_CLIENT_SECRET"])
    has_user = all(bool(os.getenv(k)) for k in ["SPO_USERNAME", "SPO_PASSWORD"])
    mode = "app" if (auth == "app" or (auth == "auto" and has_app and not has_user)) else ("userpass" if (auth == "userpass" or (auth == "auto" and has_user)) else None)
    if not mode:
        print("[red]No valid auth configured[/red]. Set either app creds (SPO_TENANT_ID, SPO_CLIENT_ID, SPO_CLIENT_SECRET) or user creds (SPO_USERNAME, SPO_PASSWORD), or pass --auth app|userpass.")
        return 1

    print(f"[bold]Site:[/bold] {site_url}")
    print(f"[bold]Mode:[/bold] {mode}")

    try:
        if mode == "app":
            upload_app_mode(site_url, src, dest_dir, fname, args.replace)
        else:
            upload_userpass_mode(site_url, src, dest_dir, fname, args.replace, args.force)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as e:
        print(f"[red]Unhandled error:[/red] {e}")
        sys.exit(1)
