"""Zabbix API routes."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from infrastructure_atlas.infrastructure.external.zabbix_client import (
    ZabbixAuthError,
    ZabbixClient,
    ZabbixClientConfig,
    ZabbixConfigError,
    ZabbixError,
)
from infrastructure_atlas.infrastructure.modules import get_module_registry

router = APIRouter(prefix="/zabbix", tags=["zabbix"])


# Module guard dependency
def require_zabbix_enabled():
    """Dependency to ensure Zabbix module is enabled."""
    registry = get_module_registry()
    try:
        registry.require_enabled("zabbix")
    except Exception as e:
        raise HTTPException(status_code=403, detail=f"Zabbix module is disabled: {e}")


def _zbx_base_url() -> str | None:
    """Get Zabbix API base URL from environment."""
    raw = os.getenv("ZABBIX_API_URL", "").strip()
    if raw:
        return raw
    host = os.getenv("ZABBIX_HOST", "").strip()
    if host:
        if host.endswith("/api_jsonrpc.php"):
            return host
        return host.rstrip("/") + "/api_jsonrpc.php"
    return None


def _zbx_web_base() -> str | None:
    """Get Zabbix web base URL from environment."""
    web = os.getenv("ZABBIX_WEB_URL", "").strip()
    if web:
        return web.rstrip("/")
    api = _zbx_base_url()
    if api and api.endswith("/api_jsonrpc.php"):
        return api[: -len("/api_jsonrpc.php")]
    return None


def _zabbix_client() -> ZabbixClient:
    """Create Zabbix client from environment configuration."""
    api_url = _zbx_base_url()
    if not api_url:
        raise HTTPException(status_code=400, detail="ZABBIX_API_URL or ZABBIX_HOST not configured")
    token = os.getenv("ZABBIX_API_TOKEN", "").strip() or None
    config = ZabbixClientConfig(
        api_url=api_url,
        api_token=token,
        web_url=_zbx_web_base(),
        timeout=30.0,
    )
    try:
        return ZabbixClient(config)
    except ZabbixConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _zbx_rpc(method: str, params: dict, *, client: ZabbixClient | None = None) -> dict:
    """Execute Zabbix JSON-RPC method."""
    client = client or _zabbix_client()
    try:
        result = client.rpc(method, params)
    except ZabbixAuthError as err:
        raise HTTPException(status_code=401, detail=f"Zabbix error: {err}") from err
    except ZabbixError as err:
        raise HTTPException(status_code=502, detail=f"Zabbix error: {err}") from err
    if isinstance(result, dict | list):
        return result  # type: ignore[return-value]
    return {}


def _zbx_expand_groupids(base_group_ids: list[int]) -> list[int]:
    """Expand group IDs to include subgroups."""
    if not base_group_ids:
        return base_group_ids
    client = _zabbix_client()
    try:
        expanded = client.expand_groupids(base_group_ids)
    except ZabbixError:
        return base_group_ids
    return list(expanded)


@router.get("/groups")
def zabbix_groups(
    name: str = Query(..., description="Group name or pattern to search for (use * for wildcards)"),
    limit: int = Query(50, ge=1, le=200),
):
    """Search Zabbix host groups by name."""
    require_zabbix_enabled()

    client = _zabbix_client()
    params: dict[str, Any] = {
        "output": ["groupid", "name"],
        "sortfield": "name",
        "limit": limit,
        "search": {"name": name},
        "searchWildcardsEnabled": True,
    }

    try:
        result = client.rpc("hostgroup.get", params)
    except ZabbixAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except ZabbixError as e:
        raise HTTPException(status_code=500, detail=str(e))

    groups = []
    if isinstance(result, list):
        for item in result:
            groupid = item.get("groupid")
            group_name = item.get("name", "")
            if groupid and group_name:
                groups.append({"groupid": int(groupid), "name": group_name})

    return {"groups": groups, "count": len(groups)}


@router.get("/host/search")
def zabbix_host_search(
    name: str = Query(..., description="Host name or pattern to search for"),
    limit: int = Query(20, ge=1, le=200),
):
    """Search Zabbix hosts by name."""
    require_zabbix_enabled()

    client = _zabbix_client()
    params: dict[str, Any] = {
        "output": ["hostid", "host", "name", "status"],
        "sortfield": "name",
        "limit": limit,
        "search": {"name": name},
        "searchWildcardsEnabled": True,
    }

    try:
        result = client.rpc("host.get", params)
    except ZabbixAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except ZabbixError as e:
        raise HTTPException(status_code=500, detail=str(e))

    hosts = []
    if isinstance(result, list):
        for item in result:
            hostid = item.get("hostid")
            hostname = item.get("host", "")
            display_name = item.get("name", hostname)
            status = item.get("status", "0")
            if hostid:
                hosts.append({
                    "hostid": int(hostid),
                    "host": hostname,
                    "name": display_name,
                    "status": "enabled" if status == "0" else "disabled",
                })

    return {"hosts": hosts, "count": len(hosts)}


@router.get("/problems")
def zabbix_problems(
    severities: str | None = Query(None, description="Comma-separated severities 0..5 (e.g. '2,3,4')"),
    groupids: str | None = Query(None, description="Comma-separated group IDs"),
    hostids: str | None = Query(None, description="Comma-separated host IDs"),
    unacknowledged: int = Query(0, ge=0, le=1),
    suppressed: int | None = Query(None, ge=0, le=1, description="Filter by suppression: None=all, 0=non-suppressed, 1=suppressed"),
    limit: int = Query(300, ge=1, le=2000),
    include_subgroups: int = Query(0, ge=0, le=1, description="When filtering by groupids, include all subgroup IDs"),
):
    """Return problems from Zabbix using problem.get with basic filters."""
    require_zabbix_enabled()

    try:
        sev_list = [int(s) for s in (severities.split(",") if severities else []) if str(s).strip() != ""]
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid severities")
    try:
        grp_list = [int(s) for s in (groupids.split(",") if groupids else []) if str(s).strip() != ""]
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid groupids")
    try:
        host_list = [int(s) for s in (hostids.split(",") if hostids else []) if str(s).strip() != ""]
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid hostids")

    if not sev_list:
        env_sev = os.getenv("ZABBIX_SEVERITIES", "2,3,4").strip()
        if env_sev:
            try:
                sev_list = [int(x) for x in env_sev.split(",") if x.strip()]
            except Exception:
                sev_list = [2, 3, 4]
        else:
            sev_list = [2, 3, 4]
    if not grp_list:
        gid = os.getenv("ZABBIX_GROUP_ID", "").strip()
        if gid.isdigit():
            grp_list = [int(gid)]

    client = _zabbix_client()
    if grp_list and include_subgroups == 1:
        grp_list = list(client.expand_groupids(grp_list))

    try:
        problem_list = client.get_problems(
            severities=sev_list,
            groupids=grp_list,
            hostids=host_list,
            unacknowledged=bool(unacknowledged),
            suppressed=bool(suppressed) if suppressed in (0, 1) else None,
            limit=limit,
        )
    except ZabbixAuthError as err:
        raise HTTPException(status_code=401, detail=f"Zabbix error: {err}") from err
    except ZabbixError as err:
        raise HTTPException(status_code=502, detail=f"Zabbix error: {err}") from err

    rows = []
    for problem in problem_list.items:
        rows.append(
            {
                "eventid": problem.event_id,
                "name": problem.name,
                "opdata": problem.opdata,
                "severity": problem.severity,
                "acknowledged": int(problem.acknowledged),
                "clock": problem.clock,
                "clock_iso": problem.clock_iso,
                "tags": list(problem.tags),
                "suppressed": int(problem.suppressed),
                "status": problem.status,
                "host": problem.host_name,
                "host_groups": [{"groupid": g.id, "name": g.name} for g in problem.host_groups],
                "hostid": problem.host_id,
                "host_url": problem.host_url,
                "problem_url": problem.problem_url,
                "duration": problem.duration,
            }
        )
    return {"items": rows, "count": len(rows)}


@router.get("/host")
def zabbix_host(hostid: int = Query(..., description="Host ID")):
    """Return extended information about a single host for debugging/analysis."""
    require_zabbix_enabled()

    try:
        host = _zabbix_client().get_host(hostid)
    except ZabbixAuthError as err:
        raise HTTPException(status_code=401, detail=f"Zabbix error: {err}") from err
    except ZabbixError as err:
        raise HTTPException(status_code=502, detail=f"Zabbix error: {err}") from err
    if not host.raw:
        raise HTTPException(status_code=404, detail="Host not found")
    return {"host": host.raw}


class ZabbixAckRequest(BaseModel):
    """Request model for acknowledging Zabbix events."""
    eventids: list[str] | list[int]
    message: str | None = None


@router.post("/ack")
def zabbix_ack(req: ZabbixAckRequest, request: Request):
    """Acknowledge one or more events in Zabbix.

    Uses event.acknowledge with action=6 (acknowledge + message). Requires API token.
    """
    require_zabbix_enabled()

    # Import here to avoid circular dependency
    from infrastructure_atlas.api.app import require_permission

    require_permission(request, "zabbix.ack")
    ids = [str(x) for x in (req.eventids or []) if str(x).strip()]
    if not ids:
        raise HTTPException(status_code=400, detail="No event IDs provided")
    try:
        result = _zabbix_client().acknowledge(ids, message=req.message)
    except ZabbixAuthError as err:
        raise HTTPException(status_code=401, detail=f"Zabbix error: {err}") from err
    except ZabbixError as err:
        raise HTTPException(status_code=502, detail=f"Zabbix error: {err}") from err
    return {"ok": True, "eventids": list(result.succeeded), "result": result.response}


@router.get("/history")
def zabbix_history(
    q: str | None = Query(None, description="Optional keyword matched against the problem or host name"),
    severities: str | None = Query(None, description="Comma-separated severities 0..5"),
    groupids: str | None = Query(None, description="Comma-separated group IDs"),
    hostids: str | None = Query(None, description="Comma-separated host IDs"),
    include_subgroups: int = Query(0, ge=0, le=1, description="Include subgroup IDs when filtering by group IDs"),
    hours: int = Query(168, ge=1, le=24 * 90, description="Number of hours to look back"),
    limit: int = Query(100, ge=1, le=500, description="Maximum number of results"),
):
    """Search recent Zabbix problems (including resolved ones) for analysis or AI tooling."""
    require_zabbix_enabled()

    try:
        sev_list = [int(s) for s in (severities.split(",") if severities else []) if str(s).strip() != ""]
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid severities")
    try:
        grp_list = [int(s) for s in (groupids.split(",") if groupids else []) if str(s).strip() != ""]
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid groupids")
    try:
        host_list = [int(s) for s in (hostids.split(",") if hostids else []) if str(s).strip() != ""]
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid hostids")

    if not sev_list:
        env_sev = os.getenv("ZABBIX_SEVERITIES", "2,3,4").strip()
        if env_sev:
            try:
                sev_list = [int(x) for x in env_sev.split(",") if x.strip()]
            except Exception:
                sev_list = [2, 3, 4]
        else:
            sev_list = [2, 3, 4]
    if not grp_list:
        gid = os.getenv("ZABBIX_GROUP_ID", "").strip()
        if gid.isdigit():
            grp_list = [int(gid)]

    lookback = datetime.now(UTC) - timedelta(hours=hours)
    time_from = int(lookback.timestamp()) if hours else None
    client = _zabbix_client()
    if grp_list and include_subgroups == 1:
        grp_list = list(client.expand_groupids(grp_list))

    # Gebruik API-zoekopdracht op naam; val terug op host-match als niets wordt gevonden.
    search_term = (q or "").strip()
    primary_search = search_term or None
    try:
        problem_list = client.get_problems(
            severities=sev_list,
            groupids=grp_list,
            hostids=host_list,
            limit=limit,
            recent=True,
            search=primary_search,
            time_from=time_from,
        )
    except ZabbixAuthError as err:
        raise HTTPException(status_code=401, detail=f"Zabbix error: {err}") from err
    except ZabbixError as err:
        raise HTTPException(status_code=502, detail=f"Zabbix error: {err}") from err

    items = list(problem_list.items)
    if search_term:
        term_lower = search_term.lower()
        filtered = [
            it for it in items if term_lower in (it.name or "").lower() or term_lower in (it.host_name or "").lower()
        ]
        if filtered:
            items = filtered
        else:
            try:
                alt = client.get_problems(
                    severities=sev_list,
                    groupids=grp_list,
                    hostids=host_list,
                    limit=limit,
                    recent=True,
                    time_from=time_from,
                )
                items = [
                    it
                    for it in alt.items
                    if term_lower in (it.name or "").lower() or term_lower in (it.host_name or "").lower()
                ]
            except ZabbixError:
                items = []

    rows = []
    for problem in items:
        rows.append(
            {
                "eventid": problem.event_id,
                "name": problem.name,
                "opdata": problem.opdata,
                "severity": problem.severity,
                "acknowledged": int(problem.acknowledged),
                "clock": problem.clock,
                "clock_iso": problem.clock_iso,
                "tags": list(problem.tags),
                "suppressed": int(problem.suppressed),
                "status": problem.status,
                "host": problem.host_name,
                "host_groups": [{"groupid": g.id, "name": g.name} for g in problem.host_groups],
                "hostid": problem.host_id,
                "host_url": problem.host_url,
                "problem_url": problem.problem_url,
                "duration": problem.duration,
            }
        )

    return {
        "items": rows,
        "count": len(rows),
        "hours": hours,
        "query": search_term,
        "limit": limit,
    }
