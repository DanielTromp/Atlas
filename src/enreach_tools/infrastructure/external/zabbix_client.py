"""Zabbix JSON-RPC client abstraction."""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import requests

from enreach_tools.domain.integrations import (
    ZabbixAckResult,
    ZabbixHost,
    ZabbixHostGroup,
    ZabbixInterface,
    ZabbixProblem,
    ZabbixProblemList,
)
from enreach_tools.domain.integrations.zabbix import JSONValue


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


class ZabbixError(Exception):
    """Base class for Zabbix-related errors."""


class ZabbixAuthError(ZabbixError):
    """Raised when Zabbix reports an authentication failure."""


class ZabbixConfigError(ZabbixError):
    """Raised when required configuration is missing."""


@dataclass(slots=True)
class ZabbixClientConfig:
    api_url: str
    api_token: str | None = None
    web_url: str | None = None
    timeout: float = 30.0


class ZabbixClient:
    def __init__(self, config: ZabbixClientConfig) -> None:
        if not config.api_url:
            raise ZabbixConfigError("Zabbix API URL is required")
        self._config = config
        self._session = requests.Session()
        self._headers = {"Content-Type": "application/json"}
        if config.api_token:
            self._headers["Authorization"] = f"Bearer {config.api_token}"

    @property
    def web_base(self) -> str | None:
        return self._config.web_url

    def rpc(self, method: str, params: Mapping[str, Any]) -> Any:
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": 1,
        }
        if self._config.api_token:
            payload["auth"] = self._config.api_token
        try:
            response = self._session.post(
                self._config.api_url,
                headers=self._headers,
                json=payload,
                timeout=self._config.timeout,
            )
        except requests.RequestException as exc:  # pragma: no cover - connectivity error
            raise ZabbixError(str(exc)) from exc
        if response.status_code == 401:
            raise ZabbixAuthError("Zabbix API returned HTTP 401 (unauthorized)")
        response.raise_for_status()
        data = response.json()
        error = data.get("error")
        if error:
            message = str(error)
            if "Not authorized" in message or "Not Authorized" in message:
                raise ZabbixAuthError(message)
            raise ZabbixError(message)
        return data.get("result", {})

    def expand_groupids(self, group_ids: Iterable[int]) -> tuple[int, ...]:
        """Return group_ids plus subgroup IDs based on name prefixes."""
        result = tuple(int(gid) for gid in group_ids if isinstance(gid, int | str))
        if not result:
            return result
        try:
            groups = self.rpc(
                "hostgroup.get",
                {"output": ["groupid", "name"], "limit": 10000},
            )
        except ZabbixError:
            return result
        if not isinstance(groups, Sequence):
            return result
        id_to_name: dict[int, str] = {}
        for g in groups:
            gid = _safe_int(_val(g, "groupid") or 0)
            nm = str(_val(g, "name") or "").strip()
            if gid:
                id_to_name[gid] = nm
        prefixes = [id_to_name.get(int(g), "").strip() for g in result]
        prefixes = [p for p in prefixes if p]
        expanded: set[int] = set(int(g) for g in result)
        if prefixes:
            for g in groups:
                gid = _safe_int(_val(g, "groupid") or 0)
                nm = str(_val(g, "name") or "").strip()
                for prefix in prefixes:
                    if nm == prefix or nm.startswith(prefix + "/"):
                        expanded.add(gid)
                        break
        return tuple(sorted(expanded))

    def get_problems(
        self,
        *,
        severities: Sequence[int] | None = None,
        groupids: Sequence[int] | None = None,
        hostids: Sequence[int] | None = None,
        unacknowledged: bool = False,
        suppressed: bool | None = None,
        limit: int = 300,
        recent: bool = False,
        search: str | None = None,
        time_from: int | None = None,
        time_till: int | None = None,
    ) -> ZabbixProblemList:
        params: dict[str, Any] = {
            "output": [
                "eventid",
                "name",
                "opdata",
                "severity",
                "clock",
                "acknowledged",
                "r_eventid",
                "source",
                "object",
                "objectid",
            ],
            "selectTags": "extend",
            "selectAcknowledges": "extend",
            "selectSuppressionData": "extend",
            "limit": limit,
        }
        if severities:
            params["severities"] = [int(s) for s in severities]
        if groupids:
            params["groupids"] = [int(g) for g in groupids]
        if hostids:
            params["hostids"] = [int(h) for h in hostids]
        if unacknowledged:
            params["acknowledged"] = 0
        if suppressed is not None:
            params["suppressed"] = 1 if suppressed else 0
        if recent:
            params["recent"] = True
        if search:
            params["search"] = {"name": search}
            params["searchWildcardsEnabled"] = "true"
        if time_from:
            params["time_from"] = int(time_from)
        if time_till:
            params["time_till"] = int(time_till)

        res = self.rpc("problem.get", params)
        problems = []
        base_web = self.web_base or ""
        trig_ids: list[str] = []
        if isinstance(res, Sequence):
            for item in res:
                val = str(_val(item, "objectid") or "").strip()
                if val and val not in trig_ids:
                    trig_ids.append(val)

        host_by_trigger: dict[str, dict[str, str | None]] = {}
        if trig_ids:
            try:
                trigs = self.rpc(
                    "trigger.get",
                    {
                        "output": ["triggerid"],
                        "selectHosts": ["hostid", "name"],
                        "triggerids": trig_ids,
                    },
                )
            except ZabbixError:
                trigs = []
            if isinstance(trigs, Sequence):
                for trig in trigs:
                    tid = str(_val(trig, "triggerid") or "")
                    hosts = trig.get("hosts") if isinstance(trig, Mapping) else None
                    if isinstance(hosts, Sequence) and hosts:
                        first = hosts[0] or {}
                        host_by_trigger[tid] = {
                            "hostid": _val(first, "hostid"),
                            "name": _val(first, "name"),
                        }

        for item in res if isinstance(res, Sequence) else []:
            clock = int(_val(item, "clock") or 0)
            event_id = str(_val(item, "eventid") or "")
            trig_id = str(_val(item, "objectid") or "")
            host_name = host_by_trigger.get(trig_id, {}).get("name")
            host_id = host_by_trigger.get(trig_id, {}).get("hostid")
            hosts_payload = item.get("hosts") if isinstance(item, Mapping) else None
            if (not host_name or not host_id) and isinstance(hosts_payload, Sequence) and hosts_payload:
                h0 = hosts_payload[0] or {}
                host_name = host_name or _val(h0, "name")
                host_id = host_id or _val(h0, "hostid")
            host_url = f"{base_web}/zabbix.php?action=host.view&hostid={host_id}" if base_web and host_id else None
            problem_url = f"{base_web}/zabbix.php?action=problem.view&eventid={event_id}" if base_web and event_id else None
            status = "RESOLVED" if str(_val(item, "r_eventid") or "0") not in {"0", "", "None"} else "PROBLEM"
            problems.append(
                ZabbixProblem(
                    event_id=event_id,
                    name=str(_val(item, "name") or ""),
                    opdata=_val(item, "opdata") or None,
                    severity=int(_val(item, "severity") or 0),
                    acknowledged=bool(int(_val(item, "acknowledged") or 0)),
                    suppressed=bool(int(_val(item, "suppressed") or 0)),
                    status=status,
                    clock=clock,
                    clock_iso=_clock_iso(clock),
                    host_name=host_name,
                    host_id=str(host_id) if host_id else None,
                    host_url=host_url,
                    problem_url=problem_url,
                    tags=_tuple_tags(item.get("tags")),
                )
            )
        problems.sort(key=lambda p: p.clock, reverse=True)
        return ZabbixProblemList(items=tuple(problems))

    def get_host(self, hostid: int | str) -> ZabbixHost:
        params = {
            "output": "extend",
            "hostids": [hostid],
            "selectInterfaces": "extend",
            "selectGroups": ["groupid", "name"],
            "selectInventory": "extend",
            "selectMacros": "extend",
            "selectTags": "extend",
        }
        res = self.rpc("host.get", params)
        if not isinstance(res, Sequence) or not res:
            raise ZabbixError("Host not found")
        payload = res[0]
        groups = tuple(
            ZabbixHostGroup(id=str(_val(g, "groupid") or ""), name=str(_val(g, "name") or ""))
            for g in payload.get("groups", [])
        )
        interfaces = tuple(
            ZabbixInterface(
                id=str(_val(itf, "interfaceid") or ""),
                ip=_val(itf, "ip") or None,
                dns=_val(itf, "dns") or None,
                main=bool(int(_val(itf, "main") or 0)),
                type=_val(itf, "type") or None,
            )
            for itf in payload.get("interfaces", [])
        )
        inventory = payload.get("inventory") if isinstance(payload.get("inventory"), Mapping) else {}
        macros = tuple(m for m in payload.get("macros", []) if isinstance(m, Mapping))
        tags = _tuple_tags(payload.get("tags"))
        return ZabbixHost(
            id=str(_val(payload, "hostid") or hostid),
            name=str(_val(payload, "name") or ""),
            technical_name=str(_val(payload, "host") or ""),
            groups=groups,
            interfaces=interfaces,
            inventory=inventory,
            macros=macros,
            tags=tags,
            raw=payload if isinstance(payload, Mapping) else {},
        )

    def acknowledge(self, event_ids: Iterable[str | int], *, message: str | None = None) -> ZabbixAckResult:
        ids = [str(eid) for eid in event_ids if str(eid).strip()]
        if not ids:
            raise ZabbixError("No event IDs provided")
        params = {
            "eventids": ids,
            "message": (message or "Acknowledged via Enreach Tools").strip(),
            "action": 6,
        }
        res = self.rpc("event.acknowledge", params)
        return ZabbixAckResult(succeeded=tuple(ids), response=res if isinstance(res, Mapping) else {})

    def search_hosts(self, pattern: str, *, limit: int = 200) -> tuple[ZabbixHost, ...]:
        params = {
            "output": ["hostid", "host", "name"],
            "search": {"name": pattern, "host": pattern},
            "searchByAny": 1,
            "searchWildcardsEnabled": 1,
            "limit": limit,
        }
        res = self.rpc("host.get", params)
        hosts: list[ZabbixHost] = []
        if isinstance(res, Sequence):
            for item in res:
                hosts.append(
                    ZabbixHost(
                        id=str(_val(item, "hostid") or ""),
                        name=str(_val(item, "name") or ""),
                        technical_name=str(_val(item, "host") or ""),
                        groups=(),
                        interfaces=(),
                        inventory={},
                        macros=(),
                        tags=(),
                        raw=item if isinstance(item, Mapping) else {},
                    )
                )
        return tuple(hosts)

    def interfaces_by_ip(self, ip: str, *, limit: int = 200) -> tuple[ZabbixInterface, ...]:
        params = {
            "output": ["interfaceid", "hostid", "ip", "dns", "type"],
            "search": {"ip": ip},
            "limit": limit,
        }
        res = self.rpc("hostinterface.get", params)
        interfaces: list[ZabbixInterface] = []
        if isinstance(res, Sequence):
            for item in res:
                interfaces.append(
                    ZabbixInterface(
                        id=str(_val(item, "interfaceid") or ""),
                        ip=_val(item, "ip") or None,
                        dns=_val(item, "dns") or None,
                        main=bool(int(_val(item, "main") or 0)),
                        type=_val(item, "type") or None,
                    )
                )
        return tuple(interfaces)

    def close(self) -> None:
        self._session.close()

    @classmethod
    def from_env(cls) -> ZabbixClient:
        import os

        raw_url = (os.getenv("ZABBIX_API_URL") or "").strip()
        host = (os.getenv("ZABBIX_HOST") or "").strip()
        if not raw_url and host:
            raw_url = host
        if raw_url and not raw_url.endswith("/api_jsonrpc.php"):
            raw_url = raw_url.rstrip("/") + "/api_jsonrpc.php"
        token = (os.getenv("ZABBIX_API_TOKEN") or "").strip() or None
        web_url = (os.getenv("ZABBIX_WEB_URL") or "").strip() or None
        if not web_url and raw_url.endswith("/api_jsonrpc.php"):
            web_url = raw_url[: -len("/api_jsonrpc.php")]
        config = ZabbixClientConfig(api_url=raw_url, api_token=token, web_url=web_url)
        return cls(config)


def _val(obj: Any, key: str) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key)
    return getattr(obj, key, None)


def _clock_iso(clock: int) -> str:
    if not clock:
        return ""
    try:
        return datetime.fromtimestamp(clock, UTC).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def _tuple_tags(payload: Any) -> tuple[Mapping[str, JSONValue], ...]:
    if isinstance(payload, Sequence):
        return tuple(item for item in payload if isinstance(item, Mapping))
    return ()


__all__ = [
    "ZabbixAuthError",
    "ZabbixClient",
    "ZabbixClientConfig",
    "ZabbixConfigError",
    "ZabbixError",
]
