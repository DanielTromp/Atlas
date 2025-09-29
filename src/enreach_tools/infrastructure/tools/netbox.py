"""LangChain tool wrappers for NetBox live search."""

from __future__ import annotations

import json
import os
from typing import Any, ClassVar, Literal

import requests
from pydantic.v1 import BaseModel, Field, validator

from enreach_tools.env import apply_extra_headers, load_env

from .base import EnreachTool, ToolConfigurationError, ToolExecutionError

__all__ = ["NetboxSearchTool"]


class _NetboxSearchArgs(BaseModel):
    dataset: Literal["devices", "vms", "all"] = Field(
        default="all",
        description="Choose the NetBox dataset to search.",
    )
    q: str = Field(..., description="Full-text query passed to NetBox's ?q= parameter.", min_length=1)
    limit: int = Field(
        default=50,
        description="Maximum rows per dataset (0 = fetch all pages, otherwise 1-5000).",
    )

    @validator("q")
    def _strip_query(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Query cannot be empty")
        return cleaned

    @validator("limit")
    def _validate_limit(cls, value: int) -> int:
        ivalue = int(value)
        if ivalue != 0 and not 1 <= ivalue <= 5000:
            raise ValueError("limit must be 0 or between 1 and 5000")
        return ivalue


class NetboxSearchTool(EnreachTool):
    name: ClassVar[str] = "netbox_live_search"
    description: ClassVar[str] = "Search NetBox directly using the built-in ?q= filter."
    args_schema: ClassVar[type[_NetboxSearchArgs]] = _NetboxSearchArgs

    def _run(self, **kwargs: Any) -> str:
        args = self.args_schema(**kwargs)
        session, base_url = self._build_session()
        max_items = None if args.limit == 0 else int(args.limit)
        try:
            rows = self._collect_rows(session, base_url, args.dataset, args.q, max_items)
        except ToolExecutionError:
            raise
        except Exception as exc:  # pragma: no cover - network/runtime errors
            raise self._handle_exception(exc)

        columns: list[str] = []
        if rows:
            columns = [col for col in rows[0].keys() if col != "ui_path"]
        payload = {
            "columns": columns,
            "rows": rows,
            "total": len(rows),
        }
        return json.dumps(payload)

    def _build_session(self) -> tuple[requests.Session, str]:
        load_env()
        base = os.getenv("NETBOX_URL", "").strip()
        token = os.getenv("NETBOX_TOKEN", "").strip()
        if not base or not token:
            raise ToolConfigurationError("NETBOX_URL and NETBOX_TOKEN must be configured")
        session = requests.Session()
        session.headers.update({"Authorization": f"Token {token}", "Accept": "application/json"})
        apply_extra_headers(session)
        return session, base.rstrip("/")

    def _collect_rows(
        self,
        session: requests.Session,
        base_url: str,
        dataset: str,
        query: str,
        max_items: int | None,
    ) -> list[dict[str, Any]]:
        if not query:
            return []
        rows: list[dict[str, Any]] = []
        if dataset in ("devices", "all"):
            devices = self._collect_pages(session, base_url, "/api/dcim/devices/", query, max_items)
            for item in devices:
                mapped = self._map_device(item)
                if dataset == "all":
                    mapped["Type"] = "device"
                rows.append(mapped)
        if dataset in ("vms", "all"):
            vms = self._collect_pages(session, base_url, "/api/virtualization/virtual-machines/", query, max_items)
            for item in vms:
                mapped = self._map_vm(item)
                if dataset == "all":
                    mapped["Type"] = "vm"
                rows.append(mapped)
        if dataset == "all":
            ips = self._collect_pages(session, base_url, "/api/ipam/ip-addresses/", query, max_items)
            for item in ips:
                rows.append(self._map_ip(item))
        return rows

    def _collect_pages(
        self,
        session: requests.Session,
        base_url: str,
        endpoint: str,
        query: str,
        max_items: int | None,
    ) -> list[dict[str, Any]]:
        from urllib.parse import quote

        items: list[dict[str, Any]] = []
        page_limit = 200
        url = f"{base_url}{endpoint}?q={quote(query)}&limit={page_limit}&offset=0"
        while url:
            resp = session.get(url, timeout=30)
            if resp.status_code in (401, 403):
                raise ToolExecutionError(f"NetBox auth failed: {resp.text[:200]}")
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", []) if isinstance(data, dict) else []
            if not isinstance(results, list):
                break
            items.extend(results)
            if max_items is not None and len(items) >= max_items:
                return items[:max_items]
            url = data.get("next") if isinstance(data, dict) else None
        return items

    def _map_device(self, payload: dict[str, Any]) -> dict[str, Any]:
        def _nested(obj: Any, *path: str) -> str:
            cur = obj
            for part in path:
                if not isinstance(cur, dict):
                    return ""
                cur = cur.get(part)
            if isinstance(cur, dict):
                for key in ("name", "label", "value", "display"):
                    if cur.get(key):
                        return str(cur[key])
                return ""
            return str(cur or "")

        def _status(val: Any) -> str:
            if isinstance(val, dict):
                return str(val.get("label") or val.get("value") or val.get("name") or "")
            return str(val or "")

        custom = payload.get("custom_fields") if isinstance(payload, dict) else {}
        oob = ""
        if isinstance(custom, dict):
            for key in (
                "oob_ip",
                "oob_ip4",
                "oob_ip6",
                "out_of_band_ip",
                "out_of_band",
                "management_ip",
                "mgmt_ip",
                "mgmt_ip4",
                "mgmt_ip6",
            ):
                value = custom.get(key)
                if value:
                    oob = str(value).strip()
                    if oob:
                        break
        pip4 = _nested(payload, "primary_ip4", "address")
        pip6 = _nested(payload, "primary_ip6", "address")
        pip = pip4 or pip6
        if not oob:
            oob = pip
        return {
            "Name": str(payload.get("name") or ""),
            "Status": _status(payload.get("status")),
            "Site": _nested(payload, "site", "name"),
            "Role": _nested(payload, "device_role", "name") or _nested(payload, "role", "name"),
            "Tenant": _nested(payload, "tenant", "name"),
            "Primary IP": pip,
            "Out-of-band IP": oob,
            "Platform": _nested(payload, "platform", "name"),
            "Device Type": _nested(payload, "device_type", "model"),
            "Updated": str(payload.get("last_updated") or ""),
            "ui_path": f"/dcim/devices/{payload.get('id')}/" if payload.get("id") is not None else "",
        }

    def _map_vm(self, payload: dict[str, Any]) -> dict[str, Any]:
        def _nested(obj: Any, *path: str) -> str:
            cur = obj
            for part in path:
                if not isinstance(cur, dict):
                    return ""
                cur = cur.get(part)
            if isinstance(cur, dict):
                for key in ("name", "label", "value", "display"):
                    if cur.get(key):
                        return str(cur[key])
                return ""
            return str(cur or "")

        def _status(val: Any) -> str:
            if isinstance(val, dict):
                return str(val.get("label") or val.get("value") or val.get("name") or "")
            return str(val or "")

        pip4 = _nested(payload, "primary_ip4", "address")
        pip6 = _nested(payload, "primary_ip6", "address")
        return {
            "Name": str(payload.get("name") or ""),
            "Status": _status(payload.get("status")),
            "Cluster": _nested(payload, "cluster", "name"),
            "Role": _nested(payload, "role", "name"),
            "Tenant": _nested(payload, "tenant", "name"),
            "Primary IP": pip4 or pip6,
            "Updated": str(payload.get("last_updated") or ""),
            "Out-of-band IP": "",
            "ui_path": f"/virtualization/virtual-machines/{payload.get('id')}/"
            if payload.get("id") is not None
            else "",
        }

    def _map_ip(self, payload: dict[str, Any]) -> dict[str, Any]:
        def _nested(obj: Any, *path: str) -> str:
            cur = obj
            for part in path:
                if not isinstance(cur, dict):
                    return ""
                cur = cur.get(part)
            if isinstance(cur, dict):
                for key in ("name", "label", "value", "display"):
                    if cur.get(key):
                        return str(cur[key])
                return ""
            return str(cur or "")

        def _status(val: Any) -> str:
            if isinstance(val, dict):
                return str(val.get("label") or val.get("value") or val.get("name") or "")
            return str(val or "")

        assigned_obj = payload.get("assigned_object") if isinstance(payload, dict) else {}
        assigned = ""
        if isinstance(assigned_obj, dict):
            assigned = str(assigned_obj.get("display") or assigned_obj.get("name") or "")
        return {
            "Name": str(payload.get("address") or ""),
            "Status": _status(payload.get("status")),
            "VRF": _nested(payload, "vrf", "name"),
            "Assigned Object": assigned,
            "Primary IP": "",
            "Out-of-band IP": "",
            "Type": "ip address",
            "Updated": str(payload.get("last_updated") or ""),
            "ui_path": f"/ipam/ip-addresses/{payload.get('id')}/" if payload.get("id") is not None else "",
        }
