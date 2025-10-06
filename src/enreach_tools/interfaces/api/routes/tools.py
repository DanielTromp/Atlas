"""API routes that expose the tool catalogue."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from enreach_tools.agents import build_tool_registry
from enreach_tools.interfaces.api.schemas import (
    ToolCatalog,
    ToolDefinition,
    ToolLink,
    ToolParameter,
)

router = APIRouter(prefix="/tools", tags=["tools"])

_TOOL_METADATA: dict[str, dict[str, Any]] = {
    "zabbix_group_search": {
        "agent": "zabbix",
        "name": "Zabbix Group Search",
        "summary": "Look up Zabbix host groups and return their IDs.",
        "description": (
            "Uses the Zabbix agent to search host groups by name so other tools can filter by ID automatically."
        ),
        "tags": ("zabbix", "monitoring", "lookup"),
        "ai_usage": "Call before fetching alerts when you only know the group name.",
        "examples": (
            "Find the Zabbix group ID for Systems Infrastructure.",
            "Search host groups containing Voice.",
        ),
        "sample": {"name": "Systems*", "limit": 20},
        "response_fields": ("groups[].groupid", "groups[].name"),
    },
    "zabbix_current_alerts": {
        "agent": "zabbix",
        "name": "Zabbix Alerts",
        "summary": "Active monitoring incidents pulled from Zabbix.",
        "description": (
            "Runs the Zabbix agent to collect live problems with optional filters for severity, host groups, and acknowledgement status."
        ),
        "tags": ("zabbix", "monitoring", "alerts"),
        "ai_usage": ("Ask for current incidents or drill into a team-specific view when triaging outages."),
        "examples": (
            "List the current high and disaster alerts in Zabbix.",
            "Show unacknowledged alerts for the Systems Infrastructure group.",
        ),
        "sample": {"limit": 50, "include_subgroups": True},
        "response_fields": (
            "items[].eventid",
            "items[].severity",
            "items[].host",
            "items[].status",
        ),
    },
    "zabbix_history_search": {
        "agent": "zabbix",
        "name": "Zabbix Alert History",
        "summary": "Recent and resolved Zabbix incidents for context.",
        "description": (
            "Leverages the Zabbix agent to query historical problems, helping with trend analysis and incident reviews."
        ),
        "tags": ("zabbix", "monitoring", "history"),
        "ai_usage": "Use for post-incident analysis or to build a timeline of related alerts.",
        "examples": (
            "Show the Zabbix alert history for pbx-core over the past 24 hours.",
            "List resolved Zabbix alerts that mentioned packet loss this week.",
        ),
        "sample": {"q": "pbx", "hours": 48, "limit": 50},
        "response_fields": (
            "items[].status",
            "items[].clock_iso",
            "items[].acknowledged",
        ),
    },
    "netbox_live_search": {
        "agent": "netbox",
        "name": "NetBox Live Search",
        "summary": "Search live inventory directly in NetBox.",
        "description": (
            "Queries NetBox via the NetBox agent to return devices, VMs, or merged views without relying on CSV exports."
        ),
        "tags": ("netbox", "inventory"),
        "ai_usage": "Great for inventory lookups during troubleshooting or change planning.",
        "examples": (
            "Find NetBox devices matching fw-core and show their primary IPs.",
            "Search NetBox VMs for anything in the management cluster.",
        ),
        "sample": {"dataset": "devices", "q": "li-core", "limit": 25},
        "response_fields": (
            "rows[].Name",
            "rows[].Primary IP",
            "rows[].Site",
        ),
    },
    "jira_issue_search": {
        "agent": "jira",
        "name": "Jira Search",
        "summary": "Run JQL-aware searches against Jira Cloud.",
        "description": (
            "The Jira agent wraps Atlassian's APIs to search incidents, problems, or changes with rich filters."
        ),
        "tags": ("jira", "issues", "atlassian"),
        "ai_usage": "Ideal for daily stand-ups or incident reviews when you need a filtered ticket list.",
        "examples": (
            "Show open high-priority Jira incidents in the SYS project.",
            "List Jira tickets assigned to me that were updated in the last 3 days.",
        ),
        "sample": {"project": "SYS", "status": "In Progress", "max_results": 20},
        "response_fields": (
            "issues[].key",
            "issues[].summary",
            "issues[].status",
        ),
        "links": (ToolLink(label="Jira UI", url="/jira"),),
    },
    "confluence_search": {
        "agent": "confluence",
        "name": "Confluence Search",
        "summary": "Locate documentation with Confluence CQL.",
        "description": (
            "The Confluence agent issues CQL queries to find pages, runbooks, and attachments for operational handovers."
        ),
        "tags": ("confluence", "knowledge", "atlassian"),
        "ai_usage": "Use when you need to surface runbooks or recent documentation updates.",
        "examples": (
            "Find Confluence pages about SIP trunk failover.",
            "Search Confluence for runbooks tagged with network and firewall.",
        ),
        "sample": {"space": "DOCS", "q": "SIP trunk", "max_results": 25},
        "response_fields": (
            "results[].title",
            "results[].space",
            "results[].url",
        ),
    },
    "export_run_job": {
        "agent": "export",
        "name": "Export Runner",
        "summary": "Trigger NetBox export pipelines from the agent layer.",
        "description": ("Runs the export agent to start CLI-based NetBox exports and returns the command summary."),
        "tags": ("export", "netbox", "automation"),
        "ai_usage": "Start a fresh NetBox export before compiling reports or distributing datasets.",
        "examples": (
            "Run the full NetBox export with a forced refresh.",
            "Export only the virtual machine inventory from NetBox.",
        ),
        "sample": {"dataset": "all", "force": False},
        "response_fields": ("command", "returncode"),
    },
    "export_status_overview": {
        "agent": "export",
        "name": "Export Status",
        "summary": "Summarise recent NetBox export artefacts.",
        "description": (
            "Uses the export agent to scan the data directory and report on the latest CSV/XLSX artefacts."
        ),
        "tags": ("export", "inventory"),
        "ai_usage": "Check whether recent exports completed before sharing files with stakeholders.",
        "examples": ("Show the 5 most recent NetBox export files and their timestamps.",),
        "sample": {"limit": 5},
        "response_fields": (
            "files[].name",
            "files[].modified_ams",
        ),
    },
    "admin_config_overview": {
        "agent": "admin",
        "name": "Admin Config Survey",
        "summary": "Inspect key configuration secrets and flags.",
        "description": (
            "Calls the admin agent to report whether required environment settings are present, without leaking secrets."
        ),
        "tags": ("admin", "configuration"),
        "ai_usage": "Run before onboarding to ensure all integrations have credentials configured.",
        "examples": ("Check which systems are missing API tokens.",),
        "sample": {"include_values": False},
        "response_fields": (
            "settings[].key",
            "settings[].configured",
        ),
    },
    "admin_backup_status": {
        "agent": "admin",
        "name": "Backup Status",
        "summary": "Report the configured backup transport and status.",
        "description": ("Uses the admin agent to summarise backup enablement, target, and authentication coverage."),
        "tags": ("admin", "backup"),
        "ai_usage": "Verify backup settings during maintenance or after changing credentials.",
        "examples": ("Confirm whether SFTP backups are fully configured.",),
        "sample": {},
        "response_fields": ("enabled", "type", "configured", "target"),
    },
}

_TOOL_REGISTRY = build_tool_registry()
_CATALOG: tuple[ToolDefinition, ...] = tuple()


def _field_type(field: Any) -> str | None:
    python_type = field.type_
    if python_type is bool:
        return "boolean"
    if python_type is int:
        return "integer"
    if python_type is float:
        return "number"
    if python_type is str:
        return "string"
    return None


def _tool_parameters(tool_key: str, tool: Any) -> tuple[ToolParameter, ...]:
    params: list[ToolParameter] = []
    schema = tool.args_schema
    fields = getattr(schema, "__fields__", {})
    for name, field in fields.items():
        param_type = _field_type(field)
        default = field.default if field.default is not None else None
        example = field.field_info.extra.get("example") if field.field_info else None
        params.append(
            ToolParameter(
                name=name,
                location="body",
                required=field.required and default is None,
                type=param_type,
                description=(field.field_info.description if field.field_info else None),
                default=default,
                example=example,
            )
        )
    return tuple(params)


def _construct_catalog() -> tuple[ToolDefinition, ...]:
    tools: list[ToolDefinition] = []
    for key, meta in _TOOL_METADATA.items():
        tool = _TOOL_REGISTRY.get(key)
        if tool is None:
            continue
        parameters = _tool_parameters(key, tool)
        links = meta.get("links") or ()
        if links and isinstance(links, tuple):
            link_objs = links
        else:
            link_objs = tuple()
        tools.append(
            ToolDefinition(
                key=key,
                name=meta["name"],
                agent=meta["agent"],
                summary=meta.get("summary", ""),
                description=meta.get("description", ""),
                method="POST",
                path=f"/tools/{key}/sample",
                tags=tuple(meta.get("tags", ())),
                parameters=parameters,
                ai_usage=meta.get("ai_usage"),
                sample=meta.get("sample"),
                response_fields=tuple(meta.get("response_fields", ())),
                links=link_objs,
                examples=tuple(meta.get("examples", ())),
            )
        )
    return tuple(tools)


_CATALOG = _construct_catalog()


def _catalog_index() -> dict[str, ToolDefinition]:
    return {tool.key: tool for tool in _CATALOG}


def _ensure_tools_access(request: Request) -> None:
    user = getattr(request.state, "user", None)
    if user is None:
        return
    if getattr(user, "role", "") == "admin":
        return
    permissions = getattr(request.state, "permissions", frozenset())
    if "tools.use" not in permissions:
        raise HTTPException(status_code=403, detail="Tools access requires additional permissions")


@router.get("", response_model=ToolCatalog)
async def list_tools(request: Request) -> ToolCatalog:
    """Return the full tool catalogue."""
    _ensure_tools_access(request)
    return ToolCatalog(tools=_CATALOG)


@router.get("/{tool_key}", response_model=ToolDefinition)
async def get_tool(tool_key: str, request: Request) -> ToolDefinition:
    catalog = _catalog_index()
    if tool_key not in catalog:
        raise HTTPException(status_code=404, detail="Tool not found")
    _ensure_tools_access(request)
    return catalog[tool_key]
