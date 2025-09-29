"""LangChain tools for Zabbix operations."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

from pydantic.v1 import BaseModel, Field, validator

from enreach_tools.env import load_env
from enreach_tools.infrastructure.external.zabbix_client import (
    ZabbixAuthError,
    ZabbixClient,
    ZabbixClientConfig,
    ZabbixConfigError,
    ZabbixError,
)

from .base import EnreachTool, ToolConfigurationError, ToolExecutionError

__all__ = ["ZabbixGroupSearchTool", "ZabbixHistoryTool", "ZabbixProblemsTool"]


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _get_value(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _build_zabbix_client() -> ZabbixClient:
    load_env()
    api_url = os.getenv("ZABBIX_API_URL", "").strip()
    api_token = os.getenv("ZABBIX_API_TOKEN", "").strip() or None
    web_url = os.getenv("ZABBIX_WEB_URL", "").strip() or os.getenv("ZABBIX_HOST", "").strip() or None
    if not api_url:
        raise ToolConfigurationError("ZABBIX_API_URL is not configured")
    try:
        return ZabbixClient(ZabbixClientConfig(api_url=api_url, api_token=api_token, web_url=web_url))
    except ZabbixConfigError as exc:
        raise ToolConfigurationError(str(exc)) from exc


class _GroupSearchArgs(BaseModel):
    name: str = Field(
        ...,
        description="Group name or wildcard pattern (use * for wildcards).",
        min_length=1,
    )
    limit: int = Field(default=50, description="Maximum number of groups to return (1-200)")

    @validator("name")
    def _clean_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name cannot be empty")
        return cleaned

    @validator("limit")
    def _validate_limit(cls, value: int) -> int:
        ivalue = int(value)
        if not 1 <= ivalue <= 200:
            raise ValueError("limit must be between 1 and 200")
        return ivalue


class ZabbixGroupSearchTool(EnreachTool):
    name: ClassVar[str] = "zabbix_group_search"
    description: ClassVar[str] = "Search Zabbix host groups and return their IDs."
    args_schema: ClassVar[type[_GroupSearchArgs]] = _GroupSearchArgs

    def _run(self, **kwargs: Any) -> str:
        args = self.args_schema(**kwargs)
        client = _build_zabbix_client()
        term = args.name
        params: dict[str, Any] = {
            "output": ["groupid", "name"],
            "sortfield": "name",
            "limit": args.limit,
            "search": {"name": term},
            "searchWildcardsEnabled": True,
        }
        try:
            result = client.rpc("hostgroup.get", params)
        except (ZabbixAuthError, ZabbixError) as exc:
            raise self._handle_exception(exc)

        groups: list[dict[str, Any]] = []
        if isinstance(result, Sequence):
            for item in result:
                gid = _safe_int(_get_value(item, "groupid") or 0)
                name = str(_get_value(item, "name") or "").strip()
                if not name:
                    continue
                if gid and name:
                    groups.append({"groupid": gid, "name": name})
        payload = {"groups": groups, "count": len(groups)}
        return json.dumps(payload)


class _ProblemsArgs(BaseModel):
    severities: str | None = Field(
        default=None,
        description="Comma separated severities (0-5). Defaults to env ZABBIX_SEVERITIES or 2,3,4.",
    )
    groupids: str | None = Field(
        default=None,
        description="Comma separated group IDs.",
    )
    hostids: str | None = Field(
        default=None,
        description="Comma separated host IDs.",
    )
    unacknowledged: bool = Field(default=False, description="Only return unacknowledged problems.")
    suppressed: bool | None = Field(default=None, description="Filter by suppression flag (True/False).")
    include_subgroups: bool = Field(
        default=False,
        description="Include subgroup IDs when group IDs are supplied.",
    )
    limit: int = Field(default=300, description="Maximum number of rows (1-2000).")

    @validator("severities", "groupids", "hostids")
    def _clean_csv(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip().strip(",")
        return stripped or None

    @validator("limit")
    def _validate_limit(cls, value: int) -> int:
        if not 1 <= int(value) <= 2000:
            raise ValueError("limit must be between 1 and 2000")
        return int(value)


class ZabbixProblemsTool(EnreachTool):
    name: ClassVar[str] = "zabbix_current_alerts"
    description: ClassVar[str] = "Fetch active problems from Zabbix, mirroring the web UI filters."
    args_schema: ClassVar[type[_ProblemsArgs]] = _ProblemsArgs

    def _run(self, **kwargs: Any) -> str:
        args = self.args_schema(**kwargs)
        client = _build_zabbix_client()
        severities = _parse_int_csv(args.severities) or _default_severities()
        groupids = _parse_int_csv(args.groupids) or _default_group_ids()
        hostids = _parse_int_csv(args.hostids)
        if groupids and args.include_subgroups:
            groupids = list(client.expand_groupids(groupids))
        try:
            problem_list = client.get_problems(
                severities=severities,
                groupids=groupids,
                hostids=hostids,
                unacknowledged=args.unacknowledged,
                suppressed=args.suppressed,
                limit=args.limit,
            )
        except (ZabbixAuthError, ZabbixError) as exc:
            raise self._handle_exception(exc)

        rows: list[dict[str, Any]] = []
        for problem in problem_list.items:
            rows.append(
                {
                    "eventid": problem.event_id,
                    "name": problem.name,
                    "opdata": problem.opdata,
                    "severity": problem.severity,
                    "acknowledged": int(problem.acknowledged),
                    "suppressed": int(problem.suppressed),
                    "status": problem.status,
                    "clock": problem.clock,
                    "clock_iso": problem.clock_iso,
                    "host": problem.host_name,
                    "hostid": problem.host_id,
                    "host_url": problem.host_url,
                    "problem_url": problem.problem_url,
                    "tags": list(problem.tags),
                }
            )
        payload = {"items": rows, "count": len(rows)}
        return json.dumps(payload)


class _HistoryArgs(BaseModel):
    q: str | None = Field(default=None, description="Keyword matched against host or problem name.")
    severities: str | None = Field(default=None, description="Comma separated severities (0-5).")
    groupids: str | None = Field(default=None, description="Comma separated group IDs.")
    hostids: str | None = Field(default=None, description="Comma separated host IDs.")
    include_subgroups: bool = Field(default=False, description="Include subgroup IDs when filtering by group IDs.")
    hours: int = Field(default=168, description="Look-back window (hours, 1-2160).")
    limit: int = Field(default=100, description="Maximum number of rows (1-500).")

    @validator("severities", "groupids", "hostids")
    def _clean_csv(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip().strip(",")
        return stripped or None

    @validator("limit")
    def _validate_history_limit(cls, value: int) -> int:
        if not 1 <= int(value) <= 500:
            raise ValueError("limit must be between 1 and 500")
        return int(value)

    @validator("hours")
    def _validate_hours(cls, value: int) -> int:
        ivalue = int(value)
        if not 1 <= ivalue <= 24 * 90:
            raise ValueError("hours must be between 1 and 2160")
        return ivalue


class ZabbixHistoryTool(EnreachTool):
    name: ClassVar[str] = "zabbix_history_search"
    description: ClassVar[str] = "Search recent (including resolved) Zabbix problems for historical context."
    args_schema: ClassVar[type[_HistoryArgs]] = _HistoryArgs

    def _run(self, **kwargs: Any) -> str:
        args = self.args_schema(**kwargs)
        client = _build_zabbix_client()
        severities = _parse_int_csv(args.severities) or _default_severities()
        groupids = _parse_int_csv(args.groupids) or _default_group_ids()
        hostids = _parse_int_csv(args.hostids)
        if groupids and args.include_subgroups:
            groupids = list(client.expand_groupids(groupids))
        try:
            problem_list = client.get_problems(
                severities=severities,
                groupids=groupids,
                hostids=hostids,
                limit=args.limit,
                recent=True,
                search=(args.q or None),
                time_from=_calculate_hours_ago(args.hours),
            )
        except (ZabbixAuthError, ZabbixError) as exc:
            raise self._handle_exception(exc)

        items = list(problem_list.items)
        if args.q:
            term = args.q.casefold()
            filtered = [
                it
                for it in items
                if (it.name and term in it.name.casefold()) or (it.host_name and term in it.host_name.casefold())
            ]
            if filtered:
                items = filtered

        rows: list[dict[str, Any]] = []
        for problem in items:
            rows.append(
                {
                    "eventid": problem.event_id,
                    "name": problem.name,
                    "opdata": problem.opdata,
                    "severity": problem.severity,
                    "acknowledged": int(problem.acknowledged),
                    "suppressed": int(problem.suppressed),
                    "status": problem.status,
                    "clock": problem.clock,
                    "clock_iso": problem.clock_iso,
                    "host": problem.host_name,
                    "hostid": problem.host_id,
                    "host_url": problem.host_url,
                    "problem_url": problem.problem_url,
                    "tags": list(problem.tags),
                }
            )
        payload = {
            "items": rows,
            "count": len(rows),
            "query": args.q or "",
            "hours": args.hours,
            "limit": args.limit,
        }
        return json.dumps(payload)


def _parse_int_csv(value: str | None) -> list[int] | None:
    if not value:
        return None
    result: list[int] = []
    for raw in value.split(","):
        chunk = raw.strip()
        if not chunk:
            continue
        try:
            result.append(int(chunk))
        except ValueError as exc:  # pragma: no cover - validation
            raise ToolExecutionError(f"Invalid integer value: {chunk}") from exc
    return result or None


def _default_severities() -> list[int]:
    env_value = os.getenv("ZABBIX_SEVERITIES", "").strip()
    parsed = _parse_int_csv(env_value)
    return parsed or [2, 3, 4]


def _default_group_ids() -> list[int] | None:
    gid = os.getenv("ZABBIX_GROUP_ID", "").strip()
    parsed = _parse_int_csv(gid)
    return parsed


def _calculate_hours_ago(hours: int) -> int:
    now = datetime.now(UTC)
    past = now - timedelta(hours=hours)
    return int(past.timestamp())
