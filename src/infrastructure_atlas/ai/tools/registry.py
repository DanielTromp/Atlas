"""Tool registry and execution for AI chat agents."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from infrastructure_atlas.ai.models import ToolCall, ToolResult
from infrastructure_atlas.infrastructure.logging import get_logger

from .definitions import ATLAS_TOOLS, get_tool_definitions

logger = get_logger(__name__)


class ToolRegistry:
    """Registry for managing and executing tools.

    The registry can execute tools either via the Atlas API or via
    direct function calls for local tools.
    """

    def __init__(
        self,
        api_base_url: str = "http://127.0.0.1:8000",
        api_token: str | None = None,
        session_cookie: str | None = None,
    ):
        self.api_base_url = api_base_url.rstrip("/")
        self.api_token = api_token
        self.session_cookie = session_cookie
        self._handlers: dict[str, Callable[..., Any]] = {}
        self._client: httpx.AsyncClient | None = None

        # Register default tool handlers
        self._register_default_handlers()

    def _register_default_handlers(self) -> None:
        """Register default API-based tool handlers."""
        # Map tool names to API endpoints
        self._api_mappings: dict[str, dict[str, Any]] = {
            "netbox_search": {
                "method": "GET",
                "endpoint": "/netbox/search",
                "params": ["q:query", "dataset", "limit"],
            },
            "zabbix_alerts": {
                "method": "GET",
                "endpoint": "/zabbix/problems",
                "params": ["limit", "severities", "groupids:group_ids", "unacknowledged:unacknowledged_only", "include_subgroups:include_subgroups"],
            },
            "zabbix_host_search": {
                "method": "GET",
                "endpoint": "/zabbix/host/search",
                "params": ["name", "limit"],
            },
            "zabbix_group_search": {
                "method": "GET",
                "endpoint": "/zabbix/groups",
                "params": ["name", "limit"],
            },
            "jira_search": {
                "method": "GET",
                "endpoint": "/jira/search",
                "params": ["q:query", "project", "status", "max:max_results"],
            },
            "search_confluence_docs": {
                "method": "POST",
                "endpoint": "/confluence-rag/search",
                "body": ["query", "top_k", "spaces", "include_citations"],
                "defaults": {"top_k": 5, "include_citations": True},
            },
            "confluence_search": {
                "method": "GET",
                "endpoint": "/confluence/search",
                "params": ["q:query", "space", "max:max_results"],
            },
            "vcenter_list_instances": {
                "method": "GET",
                "endpoint": "/vcenter/instances",
            },
            "vcenter_get_vms": {
                "method": "GET",
                "endpoint": "/vcenter/{config_id}/vms",
                "params": ["refresh"],
            },
            "search_aggregate": {
                "method": "GET",
                "endpoint": "/search/aggregate",
                "params": ["q:query", "zlimit", "jlimit", "climit", "vlimit"],
            },
            "monitoring_stats": {
                "method": "GET",
                "endpoint": "/monitoring/token-usage",
                "params": ["hours"],
            },
            "performance_metrics": {
                "method": "GET",
                "endpoint": "/monitoring/performance",
                "params": ["hours"],
            },
            # Ticket management
            "ticket_list": {
                "method": "GET",
                "endpoint": "/draft-tickets",
                "params": ["status"],
            },
            "ticket_create": {
                "method": "POST",
                "endpoint": "/draft-tickets",
                "body": ["suggested_title:title", "suggested_description:description", "suggested_priority:priority", "suggested_labels:labels", "linked_jira_key", "ai_proposal"],
            },
            "ticket_get": {
                "method": "GET",
                "endpoint": "/draft-tickets/{ticket_id}",
            },
            "ticket_update": {
                "method": "PATCH",
                "endpoint": "/draft-tickets/{ticket_id}",
                "body": ["suggested_title:title", "suggested_description:description", "suggested_priority:priority", "suggested_labels:labels"],
            },
            "ticket_search": {
                "method": "GET",
                "endpoint": "/draft-tickets",
                "params": ["q:query"],
            },
            "ticket_delete": {
                "method": "DELETE",
                "endpoint": "/draft-tickets/{ticket_id}",
            },
            # Jira advanced tools
            "jira_get_remote_links": {
                "method": "GET",
                "endpoint": "/jira/issue/{issue_key}/remotelink",
            },
            "jira_create_confluence_link": {
                "method": "POST",
                "endpoint": "/jira/issue/{issue_key}/remotelink/confluence",
                "body": ["page_id:confluence_page_id", "title", "relationship"],
            },
            "jira_delete_remote_link": {
                "method": "DELETE",
                "endpoint": "/jira/issue/{issue_key}/remotelink/{link_id}",
            },
            "jira_list_attachments": {
                "method": "GET",
                "endpoint": "/jira/issue/{issue_key}/attachments",
            },
            "jira_attach_file": {
                "method": "POST",
                "endpoint": "/jira/issue/{issue_key}/attachments/url",
                "body": ["file_url", "filename"],
            },
            # Commvault tools
            "commvault_backup_status": {
                "method": "GET",
                "endpoint": "/commvault/backup-status",
                "params": ["hostname", "hours", "limit"],
            },
            # Confluence RAG advanced tools
            "get_confluence_page": {
                "method": "GET",
                "endpoint": "/confluence-rag/page",
                "params": ["page_id", "page_title", "space_key"],
            },
            "list_confluence_spaces": {
                "method": "GET",
                "endpoint": "/confluence-rag/spaces",
            },
            "generate_guide_from_docs": {
                "method": "POST",
                "endpoint": "/confluence-rag/guide",
                "body": ["query", "max_pages"],
                "defaults": {"max_pages": 5},
            },
        }

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(60.0))
        return self._client

    def _get_headers(self) -> dict[str, str]:
        """Get request headers."""
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        return headers

    def _get_cookies(self) -> dict[str, str]:
        """Get request cookies."""
        if self.session_cookie:
            return {"session": self.session_cookie}
        return {}

    def register_handler(self, tool_name: str, handler: Callable[..., Any]) -> None:
        """Register a custom handler for a tool."""
        self._handlers[tool_name] = handler

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        """Execute a tool call and return the result."""
        start_time = time.perf_counter()

        logger.debug(
            "Executing tool",
            extra={
                "event": "tool_execute_start",
                "tool_name": tool_call.name,
                "arguments": tool_call.arguments,
            },
        )

        try:
            # Check for custom handler first
            if tool_call.name in self._handlers:
                result = await self._execute_handler(tool_call)
            # Check for API mapping
            elif tool_call.name in self._api_mappings:
                result = await self._execute_api(tool_call)
            else:
                result = {"error": f"Unknown tool: {tool_call.name}"}
                return ToolResult(
                    tool_call_id=tool_call.id,
                    tool_name=tool_call.name,
                    result=result,
                    success=False,
                    error=f"Unknown tool: {tool_call.name}",
                    duration_ms=int((time.perf_counter() - start_time) * 1000),
                )

            duration_ms = int((time.perf_counter() - start_time) * 1000)

            logger.info(
                "Tool executed successfully",
                extra={
                    "event": "tool_execute_success",
                    "tool_name": tool_call.name,
                    "duration_ms": duration_ms,
                },
            )

            return ToolResult(
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                result=result,
                success=True,
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)

            logger.error(
                "Tool execution failed",
                extra={
                    "event": "tool_execute_error",
                    "tool_name": tool_call.name,
                    "error": str(e),
                    "duration_ms": duration_ms,
                },
            )

            return ToolResult(
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                result=None,
                success=False,
                error=str(e),
                duration_ms=duration_ms,
            )

    async def _execute_handler(self, tool_call: ToolCall) -> Any:
        """Execute a custom handler."""
        handler = self._handlers[tool_call.name]
        result = handler(**tool_call.arguments)
        if hasattr(result, "__await__"):
            result = await result
        return result

    async def _execute_api(self, tool_call: ToolCall) -> Any:
        """Execute a tool via the Atlas API."""
        mapping = self._api_mappings[tool_call.name]
        method = mapping["method"]
        endpoint = mapping["endpoint"]

        # Handle path parameters
        args = dict(tool_call.arguments)

        # Apply defaults for missing arguments
        defaults = mapping.get("defaults", {})
        for key, default_value in defaults.items():
            if key not in args:
                args[key] = default_value
        for key in list(args.keys()):
            placeholder = f"{{{key}}}"
            if placeholder in endpoint:
                endpoint = endpoint.replace(placeholder, str(args.pop(key)))

        # Build query parameters
        params: dict[str, Any] = {}
        param_mappings = mapping.get("params", [])
        for param in param_mappings:
            if ":" in param:
                api_name, arg_name = param.split(":", 1)
            else:
                api_name = arg_name = param

            if arg_name in args:
                value = args[arg_name]
                if value is not None:
                    # Convert boolean to integer for API query params
                    if isinstance(value, bool):
                        value = 1 if value else 0
                    params[api_name] = value

        # Build request body for POST/PATCH/PUT
        body: dict[str, Any] | None = None
        body_mappings = mapping.get("body", [])
        if body_mappings:
            body = {}
            for body_param in body_mappings:
                if ":" in body_param:
                    api_name, arg_name = body_param.split(":", 1)
                else:
                    api_name = arg_name = body_param

                if arg_name in args:
                    value = args[arg_name]
                    if value is not None:
                        body[api_name] = value
                elif arg_name == "ai_proposal" and "rationale" in args:
                    # Special handling for ai_proposal from rationale
                    body["ai_proposal"] = {"rationale": args["rationale"]}

        # Make API request
        client = await self._get_client()
        url = f"{self.api_base_url}{endpoint}"

        if method == "GET":
            response = await client.get(
                url,
                params=params,
                headers=self._get_headers(),
                cookies=self._get_cookies(),
            )
        elif method in ("POST", "PATCH", "PUT"):
            response = await client.request(
                method,
                url,
                params=params if params else None,
                json=body,
                headers=self._get_headers(),
                cookies=self._get_cookies(),
            )
        else:
            response = await client.request(
                method,
                url,
                params=params if params else None,
                headers=self._get_headers(),
                cookies=self._get_cookies(),
            )

        response.raise_for_status()
        return response.json()

    def get_tools(self, categories: list[str] | None = None) -> list[dict[str, Any]]:
        """Get tool definitions in OpenAI format."""
        tools = get_tool_definitions(categories)
        return [tool.to_openai_format() for tool in tools]

    def get_tool_info(self) -> list[dict[str, Any]]:
        """Get information about all available tools."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "category": tool.category,
                "parameters": list(tool.parameters.get("properties", {}).keys()),
            }
            for tool in ATLAS_TOOLS
        ]

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None


# Global registry instance
_global_registry: ToolRegistry | None = None


def get_tool_registry(
    api_base_url: str = "http://127.0.0.1:8000",
    api_token: str | None = None,
    session_cookie: str | None = None,
) -> ToolRegistry:
    """Get the global tool registry."""
    global _global_registry
    if _global_registry is None:
        _global_registry = ToolRegistry(
            api_base_url=api_base_url,
            api_token=api_token,
            session_cookie=session_cookie,
        )
    return _global_registry

