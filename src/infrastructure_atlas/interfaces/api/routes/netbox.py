"""NetBox API routes."""

from __future__ import annotations

import csv
import os
from typing import Any, Literal

import duckdb
import numpy as np
import pandas as pd
import requests
from fastapi import APIRouter, HTTPException, Query

from infrastructure_atlas.infrastructure.modules import get_module_registry

router = APIRouter(tags=["netbox"])


# Import _csv_path from core routes
def _csv_path(name: str):
    """Get path to a file in the data directory."""
    from pathlib import Path

    from infrastructure_atlas.env import project_root

    root = project_root()
    raw = os.getenv("NETBOX_DATA_DIR", "data")
    path = Path(raw) if os.path.isabs(raw) else (root / raw)
    path.mkdir(parents=True, exist_ok=True)
    return path / name


def _list_records(
    csv_name: str,
    limit: int | None,
    offset: int,
    order_by: str | None,
    order_dir: Literal["asc", "desc"],
) -> list[dict]:
    """Query CSV file using DuckDB with optional ordering and pagination."""
    path = _csv_path(csv_name)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{csv_name} not found")
    # Read headers to validate order_by
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        headers = next(reader, [])
    if order_by and order_by not in headers:
        raise HTTPException(status_code=400, detail=f"Invalid order_by: {order_by}")

    ident = f'"{order_by}" {order_dir.upper()}' if order_by else None
    sql = "SELECT * FROM read_csv_auto(?, header=True)"
    params: list[Any] = [path.as_posix()]
    if ident:
        sql += f" ORDER BY {ident}"
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params.extend([int(limit), int(offset)])

    df = duckdb.query(sql, params=params).df()
    # Normalize to JSON‑safe values: NaN/NaT/±Inf -> None
    if not df.empty:
        df = df.replace([np.inf, -np.inf], np.nan)
        df = df.astype(object).where(pd.notnull(df), None)
    return df.to_dict(orient="records")


def _nb_session() -> tuple[requests.Session, str]:
    """Create authenticated NetBox API session."""
    base = os.getenv("NETBOX_URL", "").strip()
    token = os.getenv("NETBOX_TOKEN", "").strip()
    if not base or not token:
        raise HTTPException(status_code=400, detail="NETBOX_URL/NETBOX_TOKEN not configured in .env")
    sess = requests.Session()
    sess.headers.update({"Authorization": f"Token {token}", "Accept": "application/json"})
    try:
        from infrastructure_atlas.env import apply_extra_headers as _apply

        _apply(sess)
    except Exception:
        pass
    return sess, base.rstrip("/")


# Module guard dependency
def require_netbox_enabled():
    """Dependency to ensure NetBox module is enabled."""
    registry = get_module_registry()
    try:
        registry.require_enabled("netbox")
    except Exception as e:
        raise HTTPException(status_code=403, detail=f"NetBox module is disabled: {e}")


# Legacy routes at root level (for backward compatibility)
@router.get("/devices")
def devices(
    limit: int | None = Query(None, ge=1, description="Max rows to return (omit for all)"),
    offset: int = Query(0, ge=0),
    order_by: str | None = Query(None, description="Column name to order by"),
    order_dir: Literal["asc", "desc"] = Query("asc"),
):
    """List NetBox devices from CSV export."""
    require_netbox_enabled()
    return _list_records("netbox_devices_export.csv", limit, offset, order_by, order_dir)


@router.get("/vms")
def vms(
    limit: int | None = Query(None, ge=1, description="Max rows to return (omit for all)"),
    offset: int = Query(0, ge=0),
    order_by: str | None = Query(None, description="Column name to order by"),
    order_dir: Literal["asc", "desc"] = Query("asc"),
):
    """List NetBox VMs from CSV export."""
    require_netbox_enabled()
    return _list_records("netbox_vms_export.csv", limit, offset, order_by, order_dir)


@router.get("/all")
def all_merged(
    limit: int | None = Query(None, ge=1, description="Max rows to return (omit for all)"),
    offset: int = Query(0, ge=0),
    order_by: str | None = Query(None, description="Column name to order by"),
    order_dir: Literal["asc", "desc"] = Query("asc"),
):
    """List all merged NetBox data from CSV export."""
    require_netbox_enabled()
    return _list_records("netbox_merged_export.csv", limit, offset, order_by, order_dir)


@router.get("/netbox/config")
def netbox_config():
    """Return minimal NetBox config for the UI (base URL only)."""
    require_netbox_enabled()
    base = os.getenv("NETBOX_URL", "").strip()
    return {"configured": bool(base), "base_url": base}


@router.get("/netbox/search")
def netbox_search(
    dataset: Literal["devices", "vms", "all"] = Query("all"),
    q: str = Query("", description="Full-text query passed to NetBox ?q="),
    limit: int = Query(50, ge=0, le=5000, description="0 = no limit (fetch all pages)"),
):
    """Search NetBox live (no CSV) using the built-in ?q= filter.

    Returns rows with common fields across devices/VMs and a suggested column list.
    """
    require_netbox_enabled()
    if not (q and q.strip()):
        return {"columns": [], "rows": [], "total": 0}
    sess, base = _nb_session()

    def _status_label(x):
        if isinstance(x, dict):
            return x.get("label") or x.get("value") or x.get("name") or ""
        return str(x or "")

    def _get(addr):
        r = sess.get(addr, timeout=30)
        if r.status_code in {401, 403}:
            raise HTTPException(status_code=r.status_code, detail=f"NetBox auth failed: {r.text[:200]}")
        r.raise_for_status()
        return r.json()

    def _collect(endpoint: str, q: str, max_items: int | None) -> list[dict]:
        items: list[dict] = []
        # NetBox uses DRF pagination: limit/offset/next
        page_limit = 200  # reasonable page size
        url = f"{base}{endpoint}?q={requests.utils.quote(q)}&limit={page_limit}&offset=0"
        while url:
            data = _get(url)
            results = data.get("results", []) if isinstance(data, dict) else []
            if not isinstance(results, list):
                break
            items.extend(results)
            if max_items is not None and len(items) >= max_items:
                return items[:max_items]
            url = data.get("next") if isinstance(data, dict) else None
        return items

    def _map_device(it):
        name = it.get("name") or ""
        site = (it.get("site") or {}).get("name") or ""
        tenant = (it.get("tenant") or {}).get("name") or ""
        role = (it.get("device_role") or it.get("role") or {}).get("name") or ""
        status = _status_label(it.get("status"))
        pip4 = (it.get("primary_ip4") or {}).get("address") or ""
        pip6 = (it.get("primary_ip6") or {}).get("address") or ""
        pip = pip4 or pip6
        platform = (it.get("platform") or {}).get("name") or ""
        dtype = (it.get("device_type") or {}).get("model") or ""
        # Try to find an explicit out-of-band management IP from custom fields if present
        cf = it.get("custom_fields") or {}
        oob = ""
        try:
            if isinstance(cf, dict):
                # Common variants people use for OOB/IPMI management
                for key in [
                    "oob_ip",
                    "oob_ip4",
                    "oob_ip6",
                    "out_of_band_ip",
                    "out_of_band",
                    "management_ip",
                    "mgmt_ip",
                    "mgmt_ip4",
                    "mgmt_ip6",
                ]:
                    val = cf.get(key)
                    if isinstance(val, str | int | float) and str(val).strip():
                        oob = str(val).strip()
                        break
        except Exception:
            pass
        if not oob:
            oob = pip  # fallback to primary IP when no explicit OOB is found
        ui_path = f"/dcim/devices/{it.get('id')}/" if it.get("id") is not None else ""
        updated = it.get("last_updated") or it.get("last_updated") or ""
        return {
            "Name": name,
            "Status": status,
            "Site": site,
            "Role": role,
            "Tenant": tenant,
            "Primary IP": pip,
            "Out-of-band IP": oob,
            "Platform": platform,
            "Device Type": dtype,
            "Updated": updated,
            "ui_path": ui_path,
        }

    def _map_vm(it):
        name = it.get("name") or ""
        status = _status_label(it.get("status"))
        tenant = (it.get("tenant") or {}).get("name") or ""
        role = (it.get("role") or {}).get("name") or ""
        cluster = (it.get("cluster") or {}).get("name") or ""
        pip4 = (it.get("primary_ip4") or {}).get("address") or ""
        pip6 = (it.get("primary_ip6") or {}).get("address") or ""
        pip = pip4 or pip6
        ui_path = f"/virtualization/virtual-machines/{it.get('id')}/" if it.get("id") is not None else ""
        updated = it.get("last_updated") or ""
        return {
            "Name": name,
            "Status": status,
            "Cluster": cluster,
            "Role": role,
            "Tenant": tenant,
            "Primary IP": pip,
            "Updated": updated,
            "Out-of-band IP": "",
            "ui_path": ui_path,
        }

    rows: list[dict[str, Any]] = []
    try:
        max_items = None if int(limit) == 0 else int(limit)
        if dataset in ("devices", "all"):
            results = _collect("/api/dcim/devices/", q, max_items)
            for it in results:
                d = _map_device(it)
                if dataset == "all":
                    d["Type"] = "device"
                rows.append(d)
        if dataset in ("vms", "all"):
            results = _collect("/api/virtualization/virtual-machines/", q, max_items)
            for it in results:
                v = _map_vm(it)
                if dataset == "all":
                    v["Type"] = "vm"
                rows.append(v)
        # Always include IP addresses when searching 'all'
        if dataset == "all":

            def _map_ip(it: dict) -> dict[str, Any]:
                addr = it.get("address") or ""
                status = _status_label(it.get("status"))
                vrf = (it.get("vrf") or {}).get("name") or ""
                assigned = ""
                ao = it.get("assigned_object") or {}
                if isinstance(ao, dict):
                    assigned = ao.get("display") or ao.get("name") or ""
                ui_path = f"/ipam/ip-addresses/{it.get('id')}/" if it.get("id") is not None else ""
                updated = it.get("last_updated") or ""
                return {
                    "Name": addr,
                    "Status": status,
                    "VRF": vrf,
                    "Assigned Object": assigned,
                    "Primary IP": "",
                    "Out-of-band IP": "",
                    "Type": "ip address",
                    "Updated": updated,
                    "ui_path": ui_path,
                }

            ip_results = _collect("/api/ipam/ip-addresses/", q, max_items)
            for it in ip_results:
                rows.append(_map_ip(it))
    except HTTPException:
        raise
    except Exception as ex:
        raise HTTPException(status_code=502, detail=f"NetBox search error: {ex}")

    # Determine columns from first row
    columns: list[str] = []
    if rows:
        keys = list(rows[0].keys())
        # Hide internal helper field from table
        if "ui_path" in keys:
            keys.remove("ui_path")
        columns = keys
    return {"columns": columns, "rows": rows, "total": len(rows)}
