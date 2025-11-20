"""Atlas MCP Server - Model Context Protocol server for Infrastructure Atlas API."""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Resource,
    TextContent,
    Tool,
)


class AtlasAPIClient:
    """Client for the Atlas API."""

    def __init__(
        self,
        base_url: str,
        api_token: str | None = None,
        username: str | None = None,
        password: str | None = None,
        verify_ssl: bool = True,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.username = username
        self.password = password
        self.verify_ssl = verify_ssl
        self.headers = {}
        self.cookies: dict[str, str] = {}
        self._client: httpx.AsyncClient | None = None

        if api_token:
            self.headers["Authorization"] = f"Bearer {api_token}"

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create an HTTP client with session management."""
        if self._client is None:
            self._client = httpx.AsyncClient(verify=self.verify_ssl, timeout=30.0, cookies=self.cookies)

            # If username/password provided, login to get session cookie
            if self.username and self.password:
                login_url = f"{self.base_url}/auth/login"
                response = await self._client.post(
                    login_url,
                    data={"username": self.username, "password": self.password},
                    follow_redirects=False,
                )
                if response.status_code in (302, 303):
                    # Login successful, cookies are automatically stored
                    self.cookies.update(self._client.cookies)
                elif response.status_code == 200:
                    # Already logged in or different response
                    pass
                else:
                    raise RuntimeError(f"Login failed with status {response.status_code}")

        return self._client

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an HTTP request to the Atlas API."""
        url = f"{self.base_url}{endpoint}"
        client = await self._get_client()

        response = await client.request(
            method=method,
            url=url,
            headers=self.headers,
            params=params,
            json=json_data,
        )
        response.raise_for_status()
        return response.json()

    async def close(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def get_vcenter_instances(self) -> list[dict[str, Any]]:
        """List all vCenter instances."""
        return await self._request("GET", "/vcenter/instances")

    async def get_vcenter_vms(self, config_id: str, refresh: bool = False) -> dict[str, Any]:
        """Get VMs from a vCenter instance."""
        params = {"refresh": str(refresh).lower()}
        return await self._request("GET", f"/vcenter/{config_id}/vms", params=params)

    async def refresh_vcenter_inventory(self, config_id: str) -> dict[str, Any]:
        """Force refresh vCenter inventory."""
        return await self._request("POST", f"/vcenter/{config_id}/refresh")

    async def search_netbox(self, query: str, dataset: str = "all", limit: int = 25) -> dict[str, Any]:
        """Search NetBox inventory."""
        params = {"q": query, "dataset": dataset, "limit": limit}
        return await self._request("GET", "/netbox/search", params=params)

    async def get_zabbix_alerts(
        self,
        limit: int = 50,
        severities: str | None = None,
        group_ids: str | None = None,
        all_problems: bool = False,
    ) -> dict[str, Any]:
        """Get current Zabbix alerts."""
        params = {
            "limit": limit,
        }
        if severities:
            params["severities"] = severities
        if group_ids:
            params["groupids"] = group_ids
        if all_problems:
            params["all"] = "true"
        return await self._request("GET", "/zabbix/problems", params=params)

    async def search_jira(
        self,
        query: str | None = None,
        project: str | None = None,
        status: str | None = None,
        max_results: int = 50,
    ) -> dict[str, Any]:
        """Search Jira issues."""
        params = {"max": max_results}
        if query:
            params["q"] = query
        if project:
            params["project"] = project
        if status:
            params["status"] = status
        return await self._request("GET", "/jira/search", params=params)

    async def search_confluence(
        self,
        query: str,
        space: str | None = None,
        max_results: int = 25,
    ) -> dict[str, Any]:
        """Search Confluence pages."""
        params = {"q": query, "max": max_results}
        if space:
            params["space"] = space
        return await self._request("GET", "/confluence/search", params=params)

    async def search_aggregate(
        self,
        query: str,
        zlimit: int = 0,
        jlimit: int = 0,
        climit: int = 0,
        vlimit: int = 0,
    ) -> dict[str, Any]:
        """Search across all systems (Zabbix, Jira, Confluence, vCenter, NetBox).

        Default limits are 0 (unlimited) for comprehensive search results.
        """
        params = {
            "q": query,
            "zlimit": zlimit,
            "jlimit": jlimit,
            "climit": climit,
            "vlimit": vlimit,
        }
        return await self._request("GET", "/search/aggregate", params=params)

    async def get_monitoring_stats(self, hours: int = 24) -> dict[str, Any]:
        """Get token usage and monitoring statistics."""
        params = {"hours": hours}
        return await self._request("GET", "/monitoring/token-usage", params=params)

    async def get_performance_metrics(self, hours: int = 24) -> dict[str, Any]:
        """Get comprehensive performance metrics."""
        params = {"hours": hours}
        return await self._request("GET", "/monitoring/performance", params=params)

    async def get_tools_catalog(self) -> dict[str, Any]:
        """Get the full tools catalog."""
        return await self._request("GET", "/tools")


def create_server() -> Server:
    """Create and configure the Atlas MCP server."""
    import sys

    server = Server("atlas-mcp")

    # Initialize API client from environment
    base_url = os.getenv("ATLAS_API_URL", "http://127.0.0.1:8000")
    api_token = os.getenv("ATLAS_API_TOKEN")
    username = os.getenv("ATLAS_USERNAME")
    password = os.getenv("ATLAS_PASSWORD")
    verify_ssl = os.getenv("ATLAS_VERIFY_SSL", "true").lower() == "true"

    # Debug: Log configuration (to stderr so it appears in Claude Desktop logs)
    print(f"Atlas MCP Server Configuration:", file=sys.stderr)
    print(f"  URL: {base_url}", file=sys.stderr)
    print(f"  Username: {'(set)' if username else '(not set)'}", file=sys.stderr)
    print(f"  Password: {'(set)' if password else '(not set)'}", file=sys.stderr)
    print(f"  API Token: {'(set)' if api_token else '(not set)'}", file=sys.stderr)
    print(f"  Verify SSL: {verify_ssl}", file=sys.stderr)

    client = AtlasAPIClient(
        base_url=base_url,
        api_token=api_token,
        username=username,
        password=password,
        verify_ssl=verify_ssl,
    )

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        """List available Atlas tools."""
        return [
            Tool(
                name="atlas_vcenter_list_instances",
                description="List all configured vCenter instances with their status and VM counts",
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
            Tool(
                name="atlas_vcenter_get_vms",
                description="Get virtual machines from a specific vCenter instance",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "config_id": {
                            "type": "string",
                            "description": "vCenter configuration ID",
                        },
                        "refresh": {
                            "type": "boolean",
                            "description": "Force refresh from vCenter (default: false)",
                            "default": False,
                        },
                    },
                    "required": ["config_id"],
                },
            ),
            Tool(
                name="atlas_vcenter_refresh",
                description="Force refresh vCenter inventory from live vCenter API",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "config_id": {
                            "type": "string",
                            "description": "vCenter configuration ID",
                        },
                    },
                    "required": ["config_id"],
                },
            ),
            Tool(
                name="atlas_netbox_search",
                description="Search NetBox inventory (devices, VMs, or all)",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query",
                        },
                        "dataset": {
                            "type": "string",
                            "description": "Dataset to search (all, devices, vms)",
                            "enum": ["all", "devices", "vms"],
                            "default": "all",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum results to return",
                            "default": 25,
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="atlas_zabbix_alerts",
                description="Get current Zabbix monitoring alerts and problems",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Maximum alerts to return",
                            "default": 50,
                        },
                        "severities": {
                            "type": "string",
                            "description": "Comma-separated severity levels (e.g., '2,3,4')",
                        },
                        "group_ids": {
                            "type": "string",
                            "description": "Comma-separated host group IDs",
                        },
                        "all_problems": {
                            "type": "boolean",
                            "description": "Include all problems (including acknowledged)",
                            "default": False,
                        },
                    },
                },
            ),
            Tool(
                name="atlas_search_aggregate",
                description="Search across all Atlas systems (Zabbix, Jira, Confluence, vCenter, NetBox) simultaneously. Returns comprehensive results including active/historical alerts, issues, documentation, VMs, and devices. Use this for troubleshooting and finding information about infrastructure components.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query (hostname, VM name, IP address, server name, device name, or keyword)",
                        },
                        "zlimit": {
                            "type": "integer",
                            "description": "Max Zabbix results (0 = unlimited, default)",
                            "default": 0,
                        },
                        "jlimit": {
                            "type": "integer",
                            "description": "Max Jira results (0 = unlimited, default)",
                            "default": 0,
                        },
                        "climit": {
                            "type": "integer",
                            "description": "Max Confluence results (0 = unlimited, default)",
                            "default": 0,
                        },
                        "vlimit": {
                            "type": "integer",
                            "description": "Max vCenter results (0 = unlimited, default)",
                            "default": 0,
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="atlas_jira_search",
                description="Search Jira issues with filters",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query text",
                        },
                        "project": {
                            "type": "string",
                            "description": "Project key (e.g., 'SYS')",
                        },
                        "status": {
                            "type": "string",
                            "description": "Issue status filter",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum results to return",
                            "default": 20,
                        },
                    },
                },
            ),
            Tool(
                name="atlas_confluence_search",
                description="Search Confluence pages and documentation",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query",
                        },
                        "space": {
                            "type": "string",
                            "description": "Confluence space key or name",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum results to return",
                            "default": 25,
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="atlas_monitoring_stats",
                description="Get Atlas monitoring statistics including token usage and rate limits",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "hours": {
                            "type": "integer",
                            "description": "Hours of history to include",
                            "default": 24,
                        },
                    },
                },
            ),
            Tool(
                name="atlas_performance_metrics",
                description="Get comprehensive Atlas performance metrics and health status",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "hours": {
                            "type": "integer",
                            "description": "Hours of history to include",
                            "default": 24,
                        },
                    },
                },
            ),
            Tool(
                name="atlas_tools_catalog",
                description="Get the full Atlas tools catalog with all available agents and operations",
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        """Handle tool execution."""
        try:
            result = None

            if name == "atlas_vcenter_list_instances":
                result = await client.get_vcenter_instances()

            elif name == "atlas_vcenter_get_vms":
                config_id = arguments["config_id"]
                refresh = arguments.get("refresh", False)
                result = await client.get_vcenter_vms(config_id, refresh)

            elif name == "atlas_vcenter_refresh":
                config_id = arguments["config_id"]
                result = await client.refresh_vcenter_inventory(config_id)

            elif name == "atlas_netbox_search":
                query = arguments["query"]
                dataset = arguments.get("dataset", "all")
                limit = arguments.get("limit", 25)
                result = await client.search_netbox(query, dataset, limit)

            elif name == "atlas_zabbix_alerts":
                limit = arguments.get("limit", 50)
                severities = arguments.get("severities")
                group_ids = arguments.get("group_ids")
                all_problems = arguments.get("all_problems", False)
                result = await client.get_zabbix_alerts(limit, severities, group_ids, all_problems)

            elif name == "atlas_search_aggregate":
                query = arguments["query"]
                zlimit = arguments.get("zlimit", 10)
                jlimit = arguments.get("jlimit", 10)
                climit = arguments.get("climit", 10)
                vlimit = arguments.get("vlimit", 10)
                result = await client.search_aggregate(query, zlimit, jlimit, climit, vlimit)

            elif name == "atlas_jira_search":
                query = arguments.get("query")
                project = arguments.get("project")
                status = arguments.get("status")
                max_results = arguments.get("max_results", 20)
                result = await client.search_jira(query, project, status, max_results)

            elif name == "atlas_confluence_search":
                query = arguments["query"]
                space = arguments.get("space")
                max_results = arguments.get("max_results", 25)
                result = await client.search_confluence(query, space, max_results)

            elif name == "atlas_monitoring_stats":
                hours = arguments.get("hours", 24)
                result = await client.get_monitoring_stats(hours)

            elif name == "atlas_performance_metrics":
                hours = arguments.get("hours", 24)
                result = await client.get_performance_metrics(hours)

            elif name == "atlas_tools_catalog":
                result = await client.get_tools_catalog()

            else:
                return [TextContent(type="text", text=f"Unknown tool: {name}")]

            # Format result as JSON
            import json
            result_text = json.dumps(result, indent=2, default=str)

            return [TextContent(type="text", text=result_text)]

        except httpx.HTTPStatusError as e:
            error_msg = f"API Error: {e.response.status_code} - {e.response.text}"
            return [TextContent(type="text", text=error_msg)]
        except Exception as e:
            error_msg = f"Error executing {name}: {str(e)}"
            return [TextContent(type="text", text=error_msg)]

    @server.list_resources()
    async def list_resources() -> list[Resource]:
        """List available Atlas resources."""
        return [
            Resource(
                uri="atlas://vcenter/instances",
                name="vCenter Instances",
                mimeType="application/json",
                description="List of configured vCenter instances",
            ),
            Resource(
                uri="atlas://monitoring/performance",
                name="Performance Metrics",
                mimeType="application/json",
                description="Current Atlas performance metrics",
            ),
            Resource(
                uri="atlas://tools/catalog",
                name="Tools Catalog",
                mimeType="application/json",
                description="Full catalog of available Atlas tools",
            ),
        ]

    @server.read_resource()
    async def read_resource(uri: str) -> str:
        """Read a resource by URI."""
        import json

        if uri == "atlas://vcenter/instances":
            result = await client.get_vcenter_instances()
            return json.dumps(result, indent=2, default=str)

        elif uri == "atlas://monitoring/performance":
            result = await client.get_performance_metrics()
            return json.dumps(result, indent=2, default=str)

        elif uri == "atlas://tools/catalog":
            result = await client.get_tools_catalog()
            return json.dumps(result, indent=2, default=str)

        else:
            raise ValueError(f"Unknown resource URI: {uri}")

    return server


def main():
    """Run the Atlas MCP server."""
    async def run():
        async with stdio_server() as (read_stream, write_stream):
            server = create_server()
            await server.run(read_stream, write_stream, server.create_initialization_options())
    
    asyncio.run(run())


if __name__ == "__main__":
    main()
