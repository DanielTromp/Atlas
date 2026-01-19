"""Search aggregator API routes - cross-system search."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from infrastructure_atlas.application.services import create_vcenter_service
from infrastructure_atlas.infrastructure.external import ZabbixClient

from .confluence import confluence_search
from .jira import jira_search
from .netbox import netbox_search

router = APIRouter(prefix="/search", tags=["search"])


# Helper functions


def _collect_vm_search_values(vm: Any) -> list[str]:
    values: list[str] = []

    def push(raw: Any) -> None:
        if raw is None:
            return
        text = str(raw).strip().lower()
        if text:
            values.append(text)

    push(getattr(vm, "vm_id", None))
    push(getattr(vm, "name", None))
    attrs = [
        "power_state",
        "guest_os",
        "tools_status",
        "host",
        "cluster",
        "datacenter",
        "resource_pool",
        "folder",
        "instance_uuid",
        "bios_uuid",
        "guest_family",
        "guest_name",
        "guest_full_name",
        "guest_host_name",
        "guest_ip_address",
        "tools_run_state",
        "tools_version",
        "tools_version_status",
        "tools_install_type",
        "vcenter_url",
    ]
    for attr in attrs:
        push(getattr(vm, attr, None))
    for seq in (
        getattr(vm, "ip_addresses", ()) or (),
        getattr(vm, "mac_addresses", ()) or (),
        getattr(vm, "tags", ()) or (),
        getattr(vm, "network_names", ()) or (),
    ):
        for item in seq:
            push(item)
    custom_attrs = getattr(vm, "custom_attributes", None)
    if isinstance(custom_attrs, Mapping):
        for key, value in custom_attrs.items():
            push(key)
            push(value)
    return values


def _vcenter_vm_matches(vm: Any, tokens: list[str]) -> bool:
    if not tokens:
        return True
    values = _collect_vm_search_values(vm)
    if not values:
        return False
    return all(any(token in value for value in values) for token in tokens)


def _iso_datetime(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, str):
        return value
    return None


def _ts_iso(ts: int | str | None) -> str:
    try:
        t = int(ts or 0)
        if t <= 0:
            return ""
        return datetime.utcfromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


# Zabbix helper functions (duplicated for module independence)
def _zabbix_client() -> ZabbixClient:
    """Return configured Zabbix client."""
    import os

    from infrastructure_atlas.infrastructure.external import ZabbixClientConfig

    url = os.getenv("ZABBIX_API_URL", "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="Zabbix not configured: ZABBIX_API_URL is missing in .env")

    token = os.getenv("ZABBIX_API_TOKEN", "").strip() or None
    web_base = os.getenv("ZABBIX_WEB_URL", "").strip() or None

    cfg = ZabbixClientConfig(
        api_url=url,
        api_token=token,
        web_url=web_base,
        timeout=30.0,
    )
    client = ZabbixClient(cfg)
    return client


def _zbx_web_base() -> str:
    """Return Zabbix web base URL."""
    import os
    return os.getenv("ZABBIX_WEB_URL", "").strip() or ""


def _zbx_rpc(method: str, params: dict[str, Any], client: ZabbixClient | None = None) -> Any:
    """Execute Zabbix RPC method."""
    from infrastructure_atlas.infrastructure.external import ZabbixAuthError, ZabbixError

    if client is None:
        client = _zabbix_client()
    try:
        result = client.rpc(method, params)
    except ZabbixAuthError as err:
        raise HTTPException(status_code=401, detail=f"Zabbix error: {err}") from err
    except ZabbixError as err:
        raise HTTPException(status_code=502, detail=f"Zabbix error: {err}") from err
    return result


# API Routes


@router.get("/aggregate")
def search_aggregate(
    request: Request,
    q: str = Query(..., description="Object name to search across systems"),
    zlimit: int = Query(10, ge=0, le=500, description="Max Zabbix items per list (0 = no limit)"),
    jlimit: int = Query(10, ge=0, le=200, description="Max Jira issues (0 = no limit, capped upstream)"),
    climit: int = Query(10, ge=0, le=200, description="Max Confluence results (0 = no limit, capped upstream)"),
    vlimit: int = Query(10, ge=0, le=500, description="Max vCenter matches (0 = no limit)"),
):
    """Search across Zabbix, Jira, Confluence, vCenter, and NetBox for a given query."""
    out: dict[str, Any] = {"q": q}

    permissions = getattr(request.state, "permissions", frozenset())
    user = getattr(request.state, "user", None)
    user_role = getattr(user, "role", "") if user else ""
    can_view_vcenter = bool(user) and (user_role == "admin" or "vcenter.view" in permissions)
    vcenter_payload: dict[str, Any] = {
        "items": [],
        "errors": [],
        "permitted": can_view_vcenter,
        "has_more": False,
        "total": 0,
    }
    out["vcenter"] = vcenter_payload

    if can_view_vcenter and vlimit != 0:
        tokens = [token for token in q.lower().split() if token.strip()]
        try:
            # create_vcenter_service handles backend detection internally
            service = create_vcenter_service()
            configs_with_meta = service.list_configs_with_status()
            match_count = 0
            for config, _meta in configs_with_meta:
                friendly_name = config.name or config.base_url or config.id
                try:
                    _, vms, meta_payload = service.get_inventory(config.id, refresh=False)
                except Exception as exc:  # pragma: no cover - integration path
                    vcenter_payload["errors"].append(f"{friendly_name}: {exc}")
                    continue

                generated_at = None
                if isinstance(meta_payload, Mapping):
                    generated_at = _iso_datetime(meta_payload.get("generated_at"))

                for vm in vms:
                    if tokens and not _vcenter_vm_matches(vm, tokens):
                        continue
                    match_count += 1
                    if vlimit > 0 and len(vcenter_payload["items"]) >= vlimit:
                        vcenter_payload["has_more"] = True
                        break

                    vcenter_payload["items"].append(
                        {
                            "id": vm.vm_id,
                            "name": vm.name,
                            "config_id": config.id,
                            "config_name": friendly_name,
                            "power_state": vm.power_state,
                            "guest_os": vm.guest_os,
                            "tools_status": vm.tools_status,
                            "guest_host_name": vm.guest_host_name,
                            "guest_ip_address": vm.guest_ip_address,
                            "ip_addresses": list(vm.ip_addresses),
                            "mac_addresses": list(vm.mac_addresses),
                            "tags": list(vm.tags),
                            "network_names": list(vm.network_names),
                            "instance_uuid": vm.instance_uuid,
                            "bios_uuid": vm.bios_uuid,
                            "vcenter_url": vm.vcenter_url,
                            "detail_url": f"/app/vcenter/view.html?config={config.id}&vm={vm.vm_id}",
                            "generated_at": generated_at,
                        }
                    )

                if vcenter_payload["has_more"]:
                    break

            vcenter_payload["total"] = match_count
        except Exception as exc:  # pragma: no cover - defensive fallback
            vcenter_payload["errors"].append(str(exc))

        if vcenter_payload["items"]:
            vcenter_payload["items"].sort(
                key=lambda item: (
                    (item.get("name") or item.get("id") or "").lower(),
                    item.get("config_name") or "",
                )
            )

    # Zabbix: active (problems) and historical (events)
    try:
        client = _zabbix_client()
        hostids: list[int] = []
        try:
            # Fuzzy host search on both 'name' and 'host', allow partial matches and wildcards
            patt = f"*{q}*"
            res = _zbx_rpc(
                "host.get",
                {
                    "output": ["hostid", "host", "name"],
                    "search": {"name": patt, "host": patt},
                    "searchByAny": 1,
                    "searchWildcardsEnabled": 1,
                    "limit": 200,
                },
                client=client,
            )
            for h in res or []:
                try:
                    hostids.append(int(h.get("hostid")))
                except Exception:
                    pass
            # If q looks like an IP, match host interfaces by IP as well
            import re as _re

            if _re.match(r"^\d{1,3}(?:\.\d{1,3}){3}$", q.strip()):
                try:
                    intfs = _zbx_rpc(
                        "hostinterface.get",
                        {"output": ["interfaceid", "hostid", "ip"], "search": {"ip": q.strip()}, "limit": 200},
                        client=client,
                    )
                    for itf in intfs or []:
                        try:
                            hostids.append(int(itf.get("hostid")))
                        except Exception:
                            pass
                except Exception:
                    pass
            # Deduplicate
            hostids = sorted({i for i in hostids if isinstance(i, int)})
        except Exception:
            hostids = []
        zbx = {"active": [], "historical": []}
        base_web = client.web_base or _zbx_web_base() or ""
        # Active problems (prefer hostids; fallback to name search)
        p_params = {
            "output": ["eventid", "name", "severity", "clock", "acknowledged", "r_eventid"],
            "selectTags": "extend",
            "limit": 200,
        }
        if hostids:
            p_params["hostids"] = hostids
        else:
            p_params["search"] = {"name": f"*{q}*"}
            p_params["searchWildcardsEnabled"] = 1
        # Also request hosts to allow client-side fallback filtering
        p_params["selectHosts"] = ["host", "name", "hostid"]
        p = _zbx_rpc("problem.get", p_params, client=client)
        items = []
        try:
            p = sorted(p or [], key=lambda x: int(x.get("clock") or 0), reverse=True)
        except Exception:
            p = p or []
        # Apply limit
        lim = int(zlimit) if int(zlimit) > 0 else len(p)
        for it in p[:lim]:
            items.append(
                {
                    "eventid": it.get("eventid"),
                    "name": it.get("name"),
                    "severity": it.get("severity"),
                    "clock": _ts_iso(it.get("clock")),
                    "acknowledged": it.get("acknowledged"),
                    "resolved": 1 if (str(it.get("r_eventid") or "") not in ("", "0")) else 0,
                    "status": ("ACTIVE" if str(it.get("r_eventid") or "").strip() in ("", "0") else "RESOLVED"),
                    "problem_url": (
                        f"{base_web}/zabbix.php?action=problem.view&eventid={it.get('eventid')}"
                        if base_web and it.get("eventid")
                        else None
                    ),
                    "host_url": (
                        f"{base_web}/zabbix.php?action=host.view&hostid={(it.get('hosts') or [{}])[0].get('hostid')}"
                        if base_web and (it.get("hosts") or [{}])[0].get("hostid")
                        else None
                    ),
                }
            )
        # Extra fallback: if still empty and we didn't have hostids, try a broader recent scan and filter locally
        if not items and not hostids:
            try:
                alt = _zbx_rpc(
                    "problem.get",
                    {
                        "output": ["eventid", "name", "severity", "clock", "acknowledged", "r_eventid"],
                        "selectHosts": ["host", "name", "hostid"],
                        "limit": 200,
                        "sortfield": ["clock"],
                        "sortorder": "DESC",
                    },
                    client=client,
                )
                ql = q.lower().strip()
                for it in alt or []:
                    host_list = it.get("hosts", []) or []
                    host_match = any(
                        (str(h.get("host") or "") + " " + str(h.get("name") or "")).lower().find(ql) >= 0
                        for h in host_list
                    )
                    if host_match or (str(it.get("name") or "").lower().find(ql) >= 0):
                        items.append(
                            {
                                "eventid": it.get("eventid"),
                                "name": it.get("name"),
                                "severity": it.get("severity"),
                                "clock": _ts_iso(it.get("clock")),
                                "acknowledged": it.get("acknowledged"),
                                "resolved": 1 if (str(it.get("r_eventid") or "") not in ("", "0")) else 0,
                            }
                        )
            except Exception:
                pass
        zbx["active"] = items
        # Historical events (prefer hostids; fallback to name search)
        ev_params = {
            "output": ["eventid", "name", "clock", "value"],
            "selectTags": "extend",
            "source": 0,  # triggers
            "limit": 200,
        }
        if hostids:
            ev_params["hostids"] = hostids
        else:
            ev_params["search"] = {"name": f"*{q}*"}
            ev_params["searchWildcardsEnabled"] = 1
        ev = _zbx_rpc("event.get", ev_params, client=client)
        ev_items = []
        try:
            ev = sorted(ev or [], key=lambda x: int(x.get("clock") or 0), reverse=True)
        except Exception:
            ev = ev or []
        limh = int(zlimit) if int(zlimit) > 0 else len(ev)
        for it in ev[:limh]:
            ev_items.append(
                {
                    "eventid": it.get("eventid"),
                    "name": it.get("name"),
                    "clock": _ts_iso(it.get("clock")),
                    "value": it.get("value"),
                    "status": ("PROBLEM" if str(it.get("value") or "").strip() == "1" else "OK"),
                    "event_url": (
                        f"{base_web}/zabbix.php?action=event.view&eventid={it.get('eventid')}"
                        if base_web and it.get("eventid")
                        else None
                    ),
                    "host_url": (
                        f"{base_web}/zabbix.php?action=host.view&hostid={(it.get('hosts') or [{}])[0].get('hostid')}"
                        if base_web and (it.get("hosts") or [{}])[0].get("hostid")
                        else None
                    ),
                }
            )
        zbx["historical"] = ev_items
        out["zabbix"] = zbx
    except HTTPException as ex:
        out["zabbix"] = {"error": ex.detail}
    except Exception as ex:
        out["zabbix"] = {"error": str(ex)}

    # Jira: tickets containing text (last 365d to be practical)
    try:
        mr = int(jlimit) if int(jlimit) > 0 else 50
        res = jira_search(
            q=q,
            jql=None,
            project=None,
            status=None,
            assignee=None,
            priority=None,
            issuetype=None,
            updated="-365d",
            team=None,
            only_open=0,
            max_results=mr,
        )
        out["jira"] = {"total": res.get("total", 0), "issues": res.get("issues", [])}
    except HTTPException as ex:
        out["jira"] = {"error": ex.detail}
    except Exception as ex:
        out["jira"] = {"error": str(ex)}

    # Confluence: pages mentioning the object (last 365d)
    try:
        mc = int(climit) if int(climit) > 0 else 50
        res = confluence_search(q=q, space=None, ctype="page", labels=None, updated="-365d", max_results=mc)
        out["confluence"] = {"total": res.get("total", 0), "results": res.get("results", [])}
    except HTTPException as ex:
        out["confluence"] = {"error": ex.detail}
    except Exception as ex:
        out["confluence"] = {"error": str(ex)}

    # NetBox: objects matching the name; also include IPs when dataset=all
    try:
        # NetBox: no limit by default
        res = netbox_search(dataset="all", q=q, limit=0)
        out["netbox"] = {"total": res.get("total", 0), "items": res.get("rows", [])}
    except HTTPException as ex:
        out["netbox"] = {"error": ex.detail}
    except Exception as ex:
        out["netbox"] = {"error": str(ex)}

    # Commvault: jobs matching client_name or subclient_name (last 24h by default, or just recent list)
    try:
        from infrastructure_atlas.interfaces.api.routes.commvault import _load_commvault_backups

        backups_data = _load_commvault_backups()
        jobs = backups_data.get("jobs", [])
        
        cv_matches = []
        ql = q.lower().strip()
        # Search limit
        cv_limit = 50
        
        for job in jobs:
            c_name = str(job.get("client_name") or "").lower()
            dest_name = str(job.get("destination_client_name") or "").lower()
            sc_name = str(job.get("subclient_name") or "").lower()
            plan = str(job.get("plan_name") or "").lower()
            
            # Prefer destination_client_name for matching logic if we want to "see" it by that name
            # But we should search across all fields.
            # The user wants: "search isn't looking at the client_name but at the destination_client_name"
            # implying that if I search for "dest_name", I should find it.
            # And also "I want to see all the backups that are related to the server when I do a search"
            
            if ql in c_name or ql in dest_name or ql in sc_name or ql in plan:
                # Use destination client name as the primary display name if available
                display_client = job.get("destination_client_name") or job.get("client_name")
                
                cv_matches.append({
                    "job_id": job.get("job_id"),
                    "client": display_client,
                    "original_client": job.get("client_name"),
                    "type": job.get("job_type"),
                    "status": job.get("status"),
                    "start_time": job.get("start_time"),
                    "end_time": job.get("end_time"),
                    "plan": job.get("plan_name"),
                })
                if len(cv_matches) >= cv_limit:
                    break
        
        out["commvault"] = {"total": len(cv_matches), "jobs": cv_matches}
    except Exception as ex:
        out["commvault"] = {"error": str(ex)}

    return out
