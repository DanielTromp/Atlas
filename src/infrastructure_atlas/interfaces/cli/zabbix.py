"""Zabbix CLI commands."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import typer
from fastapi import HTTPException
from rich import print
from rich.console import Console
from rich.table import Table
from zoneinfo import ZoneInfo

from infrastructure_atlas.api.app import zabbix_problems as zabbix_problems_api
from infrastructure_atlas.env import load_env
from infrastructure_atlas.infrastructure.modules import get_module_registry

app = typer.Typer(help="Zabbix helpers", context_settings={"help_option_names": ["-h", "--help"]})
console = Console()

# Amsterdam timezone for display
AMS_TZ = ZoneInfo("Europe/Amsterdam")

# Zabbix severity labels
ZABBIX_SEVERITY_LABELS = [
    "Not classified",
    "Information",
    "Warning",
    "Average",
    "High",
    "Disaster",
]


@app.callback(invoke_without_command=True)
def check_module_enabled(ctx: typer.Context):
    """Ensure Zabbix module is enabled before running commands."""
    if ctx.invoked_subcommand:
        registry = get_module_registry()
        try:
            registry.require_enabled("zabbix")
        except Exception as e:
            print(f"[red]Zabbix module is disabled:[/red] {e}")
            raise typer.Exit(code=1)


def _safe_int(val: object, default: int = 0) -> int:
    """Convert value to int or return default."""
    try:
        return int(val)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _severity_label(level: object) -> str:
    """Get severity label from severity level."""
    idx = max(0, min(len(ZABBIX_SEVERITY_LABELS) - 1, _safe_int(level, 0)))
    return ZABBIX_SEVERITY_LABELS[idx]


def _zbx_dedupe_key(item: dict[str, object]) -> str:
    """Generate deduplication key for Zabbix problem."""
    name = str(item.get("name") or "").strip()
    prefix = name.split(":", 1)[0].strip() if ":" in name else name
    host_key = str(item.get("hostid") or item.get("host") or "").strip()
    if host_key and prefix:
        return f"{host_key}|{prefix}"
    if host_key:
        return f"{host_key}|{name}"
    if prefix:
        event = str(item.get("eventid") or "").strip()
        return f"{prefix}|{event}"
    return str(item.get("eventid") or "").strip()


def _apply_zabbix_gui_filter(
    items: Sequence[dict[str, object]], *, unack_only: bool
) -> list[dict[str, object]]:
    """Apply GUI-style deduplication and filtering to Zabbix problems."""
    buckets: dict[str, dict[str, object]] = {}
    for item in items:
        key = _zbx_dedupe_key(item)
        existing = buckets.get(key)
        if not existing:
            buckets[key] = item
            continue
        prev_sev = _safe_int(existing.get("severity"), -1)
        cur_sev = _safe_int(item.get("severity"), -1)
        if cur_sev > prev_sev:
            buckets[key] = item
            continue
        if cur_sev < prev_sev:
            continue
        prev_clock = _safe_int(existing.get("clock"), 0)
        cur_clock = _safe_int(item.get("clock"), 0)
        if cur_clock >= prev_clock:
            buckets[key] = item

    deduped = list(buckets.values())
    if unack_only:
        deduped = [it for it in deduped if _safe_int(it.get("acknowledged"), 0) == 0]
    deduped.sort(key=lambda it: _safe_int(it.get("clock"), 0), reverse=True)
    return deduped


def _format_zabbix_time(item: dict[str, object]) -> str:
    """Format Zabbix problem timestamp for display."""
    iso_value = str(item.get("clock_iso") or "").strip()
    dt: datetime | None = None
    if iso_value:
        try:
            dt = datetime.fromisoformat(iso_value.replace(" ", "T"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
        except Exception:
            dt = None
    if dt is None:
        clock = _safe_int(item.get("clock"), 0)
        if clock:
            try:
                dt = datetime.fromtimestamp(clock, tz=UTC)
            except Exception:
                dt = None
    if dt is None:
        return iso_value or ""
    local_dt = dt.astimezone(AMS_TZ)
    today = datetime.now(AMS_TZ).date()
    if local_dt.date() == today:
        return local_dt.strftime("%H:%M:%S")
    return local_dt.strftime("%Y-%m-%d %H:%M:%S")


def _format_zabbix_duration(clock: int) -> str:
    """Format duration since problem started."""
    now_ts = int(datetime.now(UTC).timestamp())
    seconds = max(0, now_ts - max(0, clock))
    days, remainder = divmod(seconds, 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minutes, seconds = divmod(remainder, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if not days and not hours:
        parts.append(f"{seconds}s")
    return " ".join(parts) if parts else "0s"


@app.command("dashboard")
def zabbix_dashboard_cli(
    groupids: str = typer.Option("", "--groupids", help="Comma-separated host group IDs (e.g. 27)."),
    hostids: str = typer.Option("", "--hostids", help="Comma-separated host IDs."),
    severities: str = typer.Option("", "--severities", help="Comma-separated severities 0-5 (defaults to UI config)."),
    include_subgroups: bool = typer.Option(True, "--include-subgroups/--no-include-subgroups", help="When filtering by group IDs, include all subgroups."),
    limit: int = typer.Option(300, "--limit", help="Maximum rows to fetch from the API (1-2000)."),
    unack_only: bool = typer.Option(False, "--unack-only/--include-acked", help="Match the UI toggle by filtering for unacknowledged problems after deduplication."),
    systems_only: bool = typer.Option(False, "--systems-only/--all-groups", help="Shortcut for Systems group (ID 27) including subgroups."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON payload instead of a table."),
):
    """Show the same Zabbix dashboard feed as the web UI."""

    load_env()

    gid_value = groupids.strip().strip(",")
    if systems_only:
        gid_value = gid_value or "27"
        include_subgroups = True

    host_value = hostids.strip().strip(",") or None
    sev_value = severities.strip().strip(",") or None
    gid_value_opt = gid_value or None

    include_subgroups_flag = 1 if include_subgroups and gid_value_opt else 0

    try:
        payload = zabbix_problems_api(
            severities=sev_value,
            groupids=gid_value_opt,
            hostids=host_value,
            unacknowledged=0,
            suppressed=0,
            limit=limit,
            include_subgroups=include_subgroups_flag,
        )
    except HTTPException as exc:  # pragma: no cover - runtime API failure path
        detail = exc.detail if isinstance(exc.detail, str) else json.dumps(exc.detail)
        print(f"[red]Zabbix API error:[/red] {detail}")
        raise typer.Exit(code=1)

    items = payload.get("items", [])
    filtered = _apply_zabbix_gui_filter(items, unack_only=unack_only)

    if json_output:
        typer.echo(json.dumps({"items": filtered, "count": len(filtered)}, indent=2))
        return

    if not filtered:
        print("[yellow]No problems to show[/yellow]")
        return

    table = Table(title="Zabbix Dashboard")
    table.add_column("Time", style="cyan")
    table.add_column("Severity", style="magenta")
    table.add_column("Status", style="green")
    table.add_column("Host", style="blue")
    table.add_column("Problem")
    table.add_column("Duration", style="dim")

    for item in filtered:
        time_text = _format_zabbix_time(item)
        severity_text = _severity_label(item.get("severity"))
        status_raw = (item.get("status") or "").upper() or "PROBLEM"
        if _safe_int(item.get("acknowledged"), 0):
            status_text = f"{status_raw} [dim](ack)[/dim]"
        else:
            status_text = status_raw
        host = str(item.get("host") or "-" )
        problem_name = str(item.get("name") or "")
        prob_url = str(item.get("problem_url") or "").strip()
        if prob_url:
            problem_cell = f"[link={prob_url}]{problem_name}[/link]"
        else:
            problem_cell = problem_name
        duration = _format_zabbix_duration(_safe_int(item.get("clock"), 0))
        table.add_row(time_text, severity_text, status_text, host, problem_cell, duration)

    console.print(table)
    raw_count = payload.get("count", len(items))
    summary_parts = [f"{len(filtered)} shown", f"raw {len(items)}"]
    if raw_count != len(items):
        summary_parts.append(f"API count {raw_count}")
    if unack_only:
        summary_parts.append("unacknowledged only")
    if gid_value_opt:
        summary_parts.append(f"group(s) {gid_value_opt}{' +sub' if include_subgroups_flag else ''}")
    print(f"[dim]{' — '.join(summary_parts)}[/dim]")


@app.command("problems")
def zabbix_problems_cli(
    limit: int = typer.Option(20, "--limit", help="Max items"),
    severities: str = typer.Option("", "--severities", help="Comma list, e.g. 2,3,4 (defaults from .env)"),
    groupids: str = typer.Option("", "--groupids", help="Comma list group IDs (default from .env)"),
    include_all: bool = typer.Option(False, "--all", help="Include acknowledged (unacknowledged=0)"),
):
    """Fetch problems from Zabbix via JSON-RPC and print a summary."""
    import requests as _rq
    from rich import print as _print

    from infrastructure_atlas.env import load_env as _load

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

    params: dict[str, Any] = {
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
    if not include_all:
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


@app.command("search")
def zabbix_search_cli(
    q: str = typer.Option(..., "--q", help="Substring to match in host name or problem name (wildcards enabled)"),
    limit: int = typer.Option(200, "--limit", help="Max items per call (200 typical)"),
):
    """Probe Zabbix for hosts, interfaces, problems and events matching a query.

    This mirrors the fuzzy logic used by the Search aggregator:
    - host.get search on both name and host with wildcards
    - hostinterface.get by IP when q looks like an IPv4
    - problem.get by hostids or fallback by name search with wildcards
    - event.get by hostids or fallback by name search with wildcards
    """
    import re as _re

    import requests as _rq
    from rich import print as _print

    from infrastructure_atlas.env import load_env as _load

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
    p_params: dict[str, Any] = {
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
    ev_params: dict[str, Any] = {
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
