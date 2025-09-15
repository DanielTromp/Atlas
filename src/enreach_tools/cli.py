from __future__ import annotations

import os
import subprocess
import sys

import typer
from rich import print

from .env import load_env, project_root, require_env

# Enable -h as an alias for --help everywhere
HELP_CTX = {"help_option_names": ["-h", "--help"]}

app = typer.Typer(help="Enreach Tools CLI", context_settings=HELP_CTX)


def _run_script(relpath: str, *args: str) -> int:
    """Run a Python script at repo-relative path with inherited env."""
    root = project_root()
    script = root / relpath
    if not script.exists():
        print(f"[red]Script not found:[/red] {script}")
        return 1
    cmd = [sys.executable, str(script), *args]
    return subprocess.call(cmd, cwd=root, env=os.environ.copy())


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@app.callback()
def _common(override_env: bool = typer.Option(False, "--override-env", help="Override existing env vars from .env")):
    env_path = load_env(override=override_env)
    print(f"[dim]Using .env: {env_path}[/dim]")


export = typer.Typer(help="Export helpers", context_settings=HELP_CTX)
app.add_typer(export, name="export")
api = typer.Typer(help="API server", context_settings=HELP_CTX)
app.add_typer(api, name="api")
zabbix = typer.Typer(help="Zabbix helpers", context_settings=HELP_CTX)
app.add_typer(zabbix, name="zabbix")
jira = typer.Typer(help="Jira helpers", context_settings=HELP_CTX)
app.add_typer(jira, name="jira")
confluence = typer.Typer(help="Confluence helpers", context_settings=HELP_CTX)
app.add_typer(confluence, name="confluence")
netbox = typer.Typer(help="NetBox helpers", context_settings=HELP_CTX)
app.add_typer(netbox, name="netbox")
search = typer.Typer(help="Cross-system search (Home aggregator)", context_settings=HELP_CTX)
app.add_typer(search, name="search")


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

    # Auto-publish CMDB to Confluence when configured
    try:
        base = os.getenv("ATLASSIAN_BASE_URL", "").strip()
        email = os.getenv("ATLASSIAN_EMAIL", "").strip()
        token = os.getenv("ATLASSIAN_API_TOKEN", "").strip()
        page_id = os.getenv("CONFLUENCE_CMDB_PAGE_ID", "").strip() or os.getenv("CONFLUENCE_PAGE_ID", "").strip()
        devices_page_id = os.getenv("CONFLUENCE_DEVICES_PAGE_ID", "").strip() or page_id
        vms_page_id = os.getenv("CONFLUENCE_VMS_PAGE_ID", "").strip() or os.getenv("CONFLUENCE_PAGE_ID", "").strip()
        if base and email and token and page_id:
            _ = _run_script("netbox-export/bin/confluence_publish_cmdb.py", "--page-id", page_id)
            table_args: list[str] = []
            if devices_page_id:
                table_args += ["--page-id", devices_page_id]
            _ = _run_script("netbox-export/bin/confluence_publish_devices_table.py", *table_args)
            vms_args: list[str] = []
            if vms_page_id:
                vms_args += ["--page-id", vms_page_id]
            _ = _run_script("netbox-export/bin/confluence_publish_vms_table.py", *vms_args)
        else:
            print("[dim]Confluence not configured; skipping auto publish[/dim]")
    except Exception as e:
        print(f"[red]Confluence publish failed:[/red] {e}")


@api.command("serve")
def api_serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host"),
    port: int = typer.Option(8000, "--port", help="Bind port"),
    reload: bool = typer.Option(True, "--reload/--no-reload", help="Auto-reload on changes"),
    ssl_certfile: str | None = typer.Option(
        None,
        "--ssl-certfile",
        help="Path to SSL certificate (PEM). If omitted, uses ENREACH_SSL_CERTFILE when set.",
    ),
    ssl_keyfile: str | None = typer.Option(
        None,
        "--ssl-keyfile",
        help="Path to SSL private key (PEM). If omitted, uses ENREACH_SSL_KEYFILE when set.",
    ),
    ssl_keyfile_password: str | None = typer.Option(
        None,
        "--ssl-keyfile-password",
        help="Password for encrypted SSL keyfile (optional). If omitted, uses ENREACH_SSL_KEY_PASSWORD when set.",
        show_default=False,
    ),
):
    """Run the FastAPI server (HTTP or HTTPS).

    Provide --ssl-certfile/--ssl-keyfile (or ENREACH_SSL_CERTFILE/ENREACH_SSL_KEYFILE)
    to enable HTTPS. When not provided, server runs over HTTP.
    """
    import uvicorn

    # Resolve SSL params from env when not explicitly provided
    ssl_certfile = ssl_certfile or os.getenv("ENREACH_SSL_CERTFILE") or None
    ssl_keyfile = ssl_keyfile or os.getenv("ENREACH_SSL_KEYFILE") or None
    ssl_keyfile_password = ssl_keyfile_password or os.getenv("ENREACH_SSL_KEY_PASSWORD") or None

    kwargs: dict = {"host": host, "port": port, "reload": reload}
    if ssl_certfile and ssl_keyfile:
        kwargs.update(
            {
                "ssl_certfile": ssl_certfile,
                "ssl_keyfile": ssl_keyfile,
            }
        )
        if ssl_keyfile_password:
            kwargs["ssl_keyfile_password"] = ssl_keyfile_password

    # ASGI app path: src/enreach_tools/api/app.py -> app
    uvicorn.run("enreach_tools.api.app:app", **kwargs)


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


@zabbix.command("search")
def zabbix_search_cli(
    q: str = typer.Option(..., "--q", help="Substring to match in host name or problem name (wildcards enabled)"),
    limit: int = typer.Option(200, "--limit", help="Max items per call (200 typical)"),
):
    """Probe Zabbix for hosts, interfaces, problems and events matching a query.

    This mirrors the fuzzy logic used by the Home aggregator:
    - host.get search on both name and host with wildcards
    - hostinterface.get by IP when q looks like an IPv4
    - problem.get by hostids or fallback by name search with wildcards
    - event.get by hostids or fallback by name search with wildcards
    """
    import re as _re
    import requests as _rq
    from .env import load_env as _load
    from rich import print as _print

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

    patt = f"*{q}*"
    # 1) Find matching hosts
    hosts = _rpc(
        "host.get",
        {
            "output": ["hostid", "host", "name"],
            "search": {"name": patt, "host": patt},
            "searchByAny": 1,
            "searchWildcardsEnabled": 1,
            "limit": int(limit),
        },
    ) or []
    hostids = []
    for h in hosts:
        try:
            hostids.append(int(h.get("hostid")))
        except Exception:
            pass
    # 1b) If q looks like IPv4, search interfaces by IP
    if _re.match(r"^\d{1,3}(?:\.\d{1,3}){3}$", q.strip()):
        try:
            intfs = _rpc("hostinterface.get", {"output": ["interfaceid", "hostid", "ip"], "search": {"ip": q.strip()}, "limit": int(limit)}) or []
            for itf in intfs:
                try:
                    hostids.append(int(itf.get("hostid")))
                except Exception:
                    pass
        except Exception:
            pass
    hostids = sorted({i for i in hostids if isinstance(i, int)})
    _print(f"[bold]Hosts:[/bold] {len(hostids)} matches")
    for h in hosts:
        _print(f"- id={h.get('hostid')} host={h.get('host')} name={h.get('name')}")

    # 2) Active problems
    p_params = {
        "output": ["eventid", "name", "severity", "clock", "acknowledged", "r_eventid"],
        "selectHosts": ["host", "name", "hostid"],
        "limit": int(limit),
        # Some installations disallow API sort by 'clock'; sort client-side instead
    }
    if hostids:
        p_params["hostids"] = hostids
    else:
        p_params["search"] = {"name": patt}
        p_params["searchWildcardsEnabled"] = 1
    problems = _rpc("problem.get", p_params) or []
    # Sort client-side by clock desc when present
    try:
        problems.sort(key=lambda x: int(x.get("clock") or 0), reverse=True)
    except Exception:
        pass
    _print(f"[bold]Problems:[/bold] {len(problems)} matches")
    for it in problems:
        clk = int(it.get("clock") or 0)
        from datetime import datetime as _dt
        ts = _dt.utcfromtimestamp(clk).strftime("%Y-%m-%d %H:%M:%S") if clk else "?"
        sev = it.get("severity")
        nm = it.get("name")
        hosts_disp = ", ".join([f"{h.get('host') or h.get('name')}" for h in (it.get('hosts') or [])])
        status = "ACTIVE" if str(it.get("r_eventid") or "").strip() in ("", "0") else "RESOLVED"
        _print(f"- [{ts}] [{status}] sev={sev} {nm} [dim]({hosts_disp})[/dim]")

    # 3) Historical events
    ev_params = {
        "output": ["eventid", "name", "clock", "value"],
        "selectHosts": ["host", "name", "hostid"],
        "source": 0,
        "limit": int(limit),
        # Sort client-side (some servers disallow sorting by 'clock')
    }
    if hostids:
        ev_params["hostids"] = hostids
    else:
        ev_params["search"] = {"name": patt}
        ev_params["searchWildcardsEnabled"] = 1
    events = _rpc("event.get", ev_params) or []
    try:
        events.sort(key=lambda x: int(x.get("clock") or 0), reverse=True)
    except Exception:
        pass
    _print(f"[bold]Events:[/bold] {len(events)} matches")
    for it in events[: min(len(events), 10)]:
        clk = int(it.get("clock") or 0)
        from datetime import datetime as _dt
        ts = _dt.utcfromtimestamp(clk).strftime("%Y-%m-%d %H:%M:%S") if clk else "?"
        nm = it.get("name")
        ev_status = "PROBLEM" if str(it.get("value") or "").strip() == "1" else "OK"
        hosts_disp = ", ".join([f"{h.get('host') or h.get('name')}" for h in (it.get('hosts') or [])])
        _print(f"- [{ts}] [{ev_status}] {nm} [dim]({hosts_disp})[/dim]")


@jira.command("search")
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
    from enreach_tools.api.app import jira_search as _js
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
    from rich import print as _print
    _print(f"[bold]JQL:[/bold] {res.get('jql','')}")
    issues = res.get("issues", [])
    for it in issues:
        _print(f"- [link={it.get('url','')}]" +
               f"{it.get('key','')}[/link] | {it.get('status','')} | {it.get('assignee','') or '-'} | {it.get('priority','') or '-'} | {it.get('summary','')}")
    _print(f"[dim]{len(issues)} shown (total {res.get('total', len(issues))})[/dim]")


@confluence.command("search")
def confluence_search_cli(
    q: str = typer.Option("", "--q", help="Full-text query (text ~ '...')"),
    space: str = typer.Option("", "--space", help="Space key or exact space name (comma-separated allowed)"),
    ctype: str = typer.Option("page", "--type", help="page|blogpost|attachment"),
    labels: str = typer.Option("", "--labels", help="Comma-separated labels"),
    updated: str = typer.Option("", "--updated", help="-7d, -30d, -90d or YYYY-MM-DD"),
    max_results: int = typer.Option(25, "--max", help="Max results (<=100)"),
):
    """Search Confluence content and print a concise list."""
    load_env()
    from enreach_tools.api.app import confluence_search as _cs
    res = _cs(
        q=(q or None),
        space=(space or None),
        ctype=(ctype or None),
        labels=(labels or None),
        updated=(updated or None),
        max_results=max_results,
    )
    from rich import print as _print
    _print(f"[bold]CQL:[/bold] {res.get('cql','')}")
    items = res.get("results", [])
    for it in items:
        _print(f"- [link={it.get('url','')}]" +
               f"{it.get('title','')}[/link] | {it.get('space','') or '-'} | {it.get('type','')} | {it.get('updated','') or '-'}")
    _print(f"[dim]{len(items)} shown (total {res.get('total', len(items))})[/dim]")


@confluence.command("upload")
def confluence_upload(
    file: str = typer.Option(
        "netbox-export/data/Systems CMDB.xlsx",
        "--file",
        help="Local file to upload",
    ),
    page_id: str = typer.Option(
        "",
        "--page-id",
        help="Target Confluence page ID (defaults to CONFLUENCE_CMDB_PAGE_ID)",
    ),
    name: str = typer.Option("", "--name", help="Attachment name (defaults to source filename)"),
    comment: str = typer.Option("", "--comment", help="Attachment version comment"),
):
    """Upload or replace an attachment on a Confluence page."""
    args = ["--file", file]
    if page_id:
        args += ["--page-id", page_id]
    if name:
        args += ["--name", name]
    if comment:
        args += ["--comment", comment]
    code = _run_script("netbox-export/bin/confluence_upload_attachment.py", *args)
    raise SystemExit(code)


def main():  # entry point for console_scripts
    app()


@confluence.command("publish-cmdb")
def confluence_publish_cmdb(
    page_id: str = typer.Option("", "--page-id", help="Override target page ID"),
    name: str = typer.Option("Systems CMDB.xlsx", "--name", help="Attachment name"),
    comment: str = typer.Option("", "--comment", help="Attachment version comment"),
):
    """Publish the standard NetBox CMDB Excel to Confluence."""
    args: list[str] = []
    if page_id:
        args += ["--page-id", page_id]
    if name:
        args += ["--name", name]
    if comment:
        args += ["--comment", comment]
    code = _run_script("netbox-export/bin/confluence_publish_cmdb.py", *args)
    raise SystemExit(code)


@confluence.command("publish-devices-table")
def confluence_publish_devices_table(
    csv: str = typer.Option(
        "netbox-export/data/netbox_devices_export.csv",
        "--csv",
        help="Path to the NetBox devices CSV",
    ),
    page_id: str = typer.Option("", "--page-id", help="Target Confluence page ID"),
    heading: str = typer.Option("NetBox Devices Export", "--heading", help="Heading placed above the table"),
    limit: int | None = typer.Option(None, "--limit", help="Limit number of rows (defaults to all)"),
    filter_macro: bool | None = typer.Option(None, "--filter/--no-filter", help="Wrap in Table Filter macro"),
    sort_macro: bool | None = typer.Option(None, "--sort/--no-sort", help="Wrap in Table Sort macro"),
    message: str = typer.Option("Updated NetBox devices table", "--message", help="Confluence version comment"),
    minor: bool = typer.Option(True, "--minor/--major", help="Mark update as minor edit"),
):
    """Publish the devices CSV as a Confluence table (with optional filter/sort macros)."""
    if filter_macro is None:
        filter_macro = _env_flag("CONFLUENCE_ENABLE_TABLE_FILTER", False)
    if sort_macro is None:
        sort_macro = _env_flag("CONFLUENCE_ENABLE_TABLE_SORT", False)
    args: list[str] = ["--csv", csv]
    if page_id:
        args += ["--page-id", page_id]
    if heading:
        args += ["--heading", heading]
    if limit is not None:
        args += ["--limit", str(limit)]
    args.append("--filter" if filter_macro else "--no-filter")
    args.append("--sort" if sort_macro else "--no-sort")
    if message:
        args += ["--message", message]
    if not minor:
        args.append("--major")
    code = _run_script("netbox-export/bin/confluence_publish_devices_table.py", *args)
    raise SystemExit(code)


@confluence.command("publish-vms-table")
def confluence_publish_vms_table(
    csv: str = typer.Option(
        "netbox-export/data/netbox_vms_export.csv",
        "--csv",
        help="Path to the NetBox VMs CSV",
    ),
    page_id: str = typer.Option("", "--page-id", help="Target Confluence page ID"),
    heading: str = typer.Option("NetBox VMs Export", "--heading", help="Heading placed above the table"),
    limit: int | None = typer.Option(None, "--limit", help="Limit number of rows (defaults to all)"),
    filter_macro: bool | None = typer.Option(None, "--filter/--no-filter", help="Wrap in Table Filter macro"),
    sort_macro: bool | None = typer.Option(None, "--sort/--no-sort", help="Wrap in Table Sort macro"),
    message: str = typer.Option("Updated NetBox VMs table", "--message", help="Confluence version comment"),
    minor: bool = typer.Option(True, "--minor/--major", help="Mark update as minor edit"),
):
    """Publish the VMs CSV as a Confluence table (with optional filter/sort macros)."""
    if filter_macro is None:
        filter_macro = _env_flag("CONFLUENCE_ENABLE_TABLE_FILTER", False)
    if sort_macro is None:
        sort_macro = _env_flag("CONFLUENCE_ENABLE_TABLE_SORT", False)
    args: list[str] = ["--csv", csv]
    if page_id:
        args += ["--page-id", page_id]
    if heading:
        args += ["--heading", heading]
    if limit is not None:
        args += ["--limit", str(limit)]
    args.append("--filter" if filter_macro else "--no-filter")
    args.append("--sort" if sort_macro else "--no-sort")
    if message:
        args += ["--message", message]
    if not minor:
        args.append("--major")
    code = _run_script("netbox-export/bin/confluence_publish_vms_table.py", *args)
    raise SystemExit(code)


@netbox.command("search")
def netbox_search_cli(
    q: str = typer.Option(..., "--q", help="Full-text query"),
    dataset: str = typer.Option("all", "--dataset", help="all|devices|vms"),
    limit: int = typer.Option(50, "--limit", help="0 = no limit (fetch all pages)"),
):
    """Search NetBox live via the API (no CSV)."""
    load_env()
    from enreach_tools.api.app import netbox_search as _nb
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


@netbox.command("device-json")
def netbox_device_json(
    id: int = typer.Option(0, "--id", help="Device ID"),
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
    base = base.rstrip('/')
    sess = _rq.Session()
    sess.headers.update({"Authorization": f"Token {token}", "Accept": "application/json"})
    def _get(u: str):
        r = sess.get(u, timeout=30)
        r.raise_for_status()
        return r.json()
    data = None
    if id:
        data = _get(f"{base}/api/dcim/devices/{id}/")
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


@search.command("run")
def search_run(
    q: str = typer.Option(..., "--q", "-q", help="Object name or keyword (e.g. device, vm, IP, substring)"),
    zlimit: int = typer.Option(0, "--zlimit", help="Zabbix max items (0 = no limit)"),
    jlimit: int = typer.Option(0, "--jlimit", help="Jira max issues (0 = no limit)"),
    climit: int = typer.Option(0, "--climit", help="Confluence max results (0 = no limit)"),
    json_out: bool = typer.Option(False, "--json", help="Output full JSON with all available fields"),
    out: str = typer.Option("", "--out", help="Save full JSON to file (pretty-printed)"),
):
    """Run the Home search aggregator across Zabbix, Jira, Confluence, and NetBox.

    Defaults: unlimited (zlimit/jlimit/climit = 0). Use --json for full details.
    """
    load_env()
    from enreach_tools.api.app import home_aggregate as _agg
    res = _agg(q=q, zlimit=zlimit, jlimit=jlimit, climit=climit)
    # Save to file when requested (pretty JSON)
    if out:
        import json as _json, pathlib as _pl
        path = _pl.Path(out)
        try:
            path.write_text(_json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[green]Saved:[/green] {path}")
        except Exception as e:
            print(f"[red]Failed to write {path}:[/red] {e}")
    if json_out:
        import json as _json
        print(_json.dumps(res, ensure_ascii=False, indent=2))
        return
    from rich import print as _print
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
        nm = it.get('Name') or ''
        typ = it.get('Type') or ''
        upd = it.get('Updated') or ''
        _print(f"  - {nm} {f'({typ})' if typ else ''} [dim]{upd}[/dim]")
