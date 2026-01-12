"""
Unified Atlas MCP Server for Claude integration.

This server provides direct access to all Atlas infrastructure systems:
- Confluence RAG (semantic search with citations)
- NetBox (devices, VMs, IP search)
- vCenter (VM inventory)
- Zabbix (monitoring alerts)
- Jira (issue search, attachments, remote links)
- Confluence (basic CQL search)
- Commvault (backup status)
- Cross-system unified search

Unlike the TypeScript MCP proxy, this Python server accesses systems directly
without requiring the Atlas API server to be running.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime
from typing import Any

from mcp.server.fastmcp import FastMCP

from infrastructure_atlas.confluence_rag.config import ConfluenceRAGSettings
from infrastructure_atlas.confluence_rag.database import Database
from infrastructure_atlas.confluence_rag.search import HybridSearchEngine, SearchConfig, SearchResponse

logger = logging.getLogger(__name__)


# =============================================================================
# Client Caching - Reuse clients across calls for performance
# =============================================================================

_client_cache: dict[str, Any] = {}


def _get_cached_client(key: str, factory):
    """Get or create a cached client instance."""
    if key not in _client_cache:
        _client_cache[key] = factory()
    return _client_cache[key]


# =============================================================================
# Client Factory Functions
# =============================================================================


def _create_netbox_client():
    """Create or get cached NetBox client from environment variables."""

    def factory():
        from infrastructure_atlas.infrastructure.external import NetboxClient, NetboxClientConfig

        url = os.getenv("NETBOX_URL", "").strip()
        token = os.getenv("NETBOX_TOKEN", "").strip()

        if not url or not token:
            raise ValueError("NetBox not configured: set NETBOX_URL and NETBOX_TOKEN environment variables")

        config = NetboxClientConfig(url=url, token=token, cache_ttl_seconds=600.0)  # 10 min cache
        return NetboxClient(config)

    return _get_cached_client("netbox", factory)


def _create_zabbix_client():
    """Create or get cached Zabbix client from environment variables."""

    def factory():
        from infrastructure_atlas.infrastructure.external import ZabbixClient, ZabbixClientConfig

        url = os.getenv("ZABBIX_API_URL", "").strip()
        host = os.getenv("ZABBIX_HOST", "").strip()
        if not url and host:
            url = host
        if url and not url.endswith("/api_jsonrpc.php"):
            url = url.rstrip("/") + "/api_jsonrpc.php"

        if not url:
            raise ValueError("Zabbix not configured: set ZABBIX_API_URL environment variable")

        token = os.getenv("ZABBIX_API_TOKEN", "").strip() or None
        web_url = os.getenv("ZABBIX_WEB_URL", "").strip() or None
        if not web_url and url.endswith("/api_jsonrpc.php"):
            web_url = url[: -len("/api_jsonrpc.php")]

        config = ZabbixClientConfig(api_url=url, api_token=token, web_url=web_url)
        return ZabbixClient(config)

    return _get_cached_client("zabbix", factory)


def _create_jira_client():
    """Create Jira client from environment variables."""
    from infrastructure_atlas.infrastructure.external import JiraClient, JiraClientConfig

    base_url = os.getenv("ATLASSIAN_BASE_URL", "").strip() or os.getenv("JIRA_BASE_URL", "").strip()
    email = os.getenv("ATLASSIAN_EMAIL", "").strip() or os.getenv("JIRA_EMAIL", "").strip()
    api_token = os.getenv("ATLASSIAN_API_TOKEN", "").strip() or os.getenv("JIRA_API_TOKEN", "").strip()

    if not (base_url and email and api_token):
        raise ValueError(
            "Jira not configured: set ATLASSIAN_BASE_URL, ATLASSIAN_EMAIL, ATLASSIAN_API_TOKEN environment variables"
        )

    config = JiraClientConfig(base_url=base_url, email=email, api_token=api_token)
    return JiraClient(config)


def _create_commvault_client():
    """Create or get cached Commvault client from environment variables."""

    def factory():
        from infrastructure_atlas.infrastructure.external import CommvaultClient, CommvaultClientConfig

        base_url = os.getenv("COMMVAULT_BASE_URL", "").strip()
        api_token = os.getenv("COMMVAULT_API_TOKEN", "").strip()

        if not base_url:
            raise ValueError("Commvault not configured: set COMMVAULT_BASE_URL environment variable")

        config = CommvaultClientConfig(base_url=base_url, authtoken=api_token if api_token else None)
        return CommvaultClient(config)

    return _get_cached_client("commvault", factory)


def _get_confluence_session():
    """Create authenticated Confluence session."""
    import requests

    base_url = os.getenv("ATLASSIAN_BASE_URL", "").strip()
    email = os.getenv("ATLASSIAN_EMAIL", "").strip()
    api_token = os.getenv("ATLASSIAN_API_TOKEN", "").strip()

    if not (base_url and email and api_token):
        raise ValueError(
            "Confluence not configured: set ATLASSIAN_BASE_URL, ATLASSIAN_EMAIL, ATLASSIAN_API_TOKEN environment variables"
        )

    sess = requests.Session()
    sess.auth = (email, api_token)
    sess.headers.update({"Accept": "application/json"})
    return sess, base_url.rstrip("/")


# =============================================================================
# Helper Functions
# =============================================================================


def _format_size(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def _format_datetime(dt: datetime | None) -> str:
    """Format datetime for display."""
    if dt is None:
        return "N/A"
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _severity_label(sev: int) -> str:
    """Convert Zabbix severity number to label."""
    labels = {
        0: "Not classified",
        1: "Information",
        2: "Warning",
        3: "Average",
        4: "High",
        5: "Disaster",
    }
    return labels.get(sev, f"Unknown ({sev})")


# =============================================================================
# Main MCP Server Class
# =============================================================================


class AtlasMCPServer:
    """
    Unified MCP Server for Atlas infrastructure access.

    Provides tools for:
    - Confluence RAG (semantic documentation search)
    - NetBox (DCIM/IPAM)
    - vCenter (virtualization)
    - Zabbix (monitoring)
    - Jira (issue tracking)
    - Confluence (basic wiki search)
    - Commvault (backup)
    """

    def __init__(
        self,
        search_engine: HybridSearchEngine | None = None,
        db: Database | None = None,
        settings: ConfluenceRAGSettings | None = None,
    ):
        self.search = search_engine
        self.db = db
        self.settings = settings
        self.server = FastMCP("atlas-infrastructure")
        self._register_tools()

    def _register_tools(self):
        """Register all MCP tools."""

        # =====================================================================
        # Confluence RAG Tools (semantic search)
        # =====================================================================

        if self.search and self.db:
            self._register_confluence_rag_tools()

        # =====================================================================
        # NetBox Tools
        # =====================================================================

        @self.server.tool()
        async def atlas_netbox_search(query: str, limit: int = 50) -> str:
            """
            Search NetBox for devices, VMs, or IP addresses.

            Args:
                query: Search query (hostname, IP, or partial name)
                limit: Maximum results to return (default 50)

            Returns:
                Matching devices and VMs from NetBox
            """
            try:
                client = _create_netbox_client()
            except ValueError as e:
                return f"## Error: NetBox Not Configured\n\n{e}"

            results = []
            query_stripped = query.strip()

            def _search_devices():
                """Server-side device search using NetBox API."""
                try:
                    # Use pynetbox's filter with 'q' parameter for server-side search
                    raw_devices = list(client.api.dcim.devices.filter(q=query_stripped, limit=limit))
                    for device in raw_devices:
                        data = device.serialize() if hasattr(device, "serialize") else {}
                        status_obj = data.get("status", {})
                        status_label = (
                            status_obj.get("label")
                            if isinstance(status_obj, dict)
                            else str(status_obj)
                            if status_obj
                            else None
                        )
                        role_obj = data.get("role", {})
                        role = (
                            role_obj.get("name") if isinstance(role_obj, dict) else str(role_obj) if role_obj else None
                        )
                        site_obj = data.get("site", {})
                        site = (
                            site_obj.get("name") if isinstance(site_obj, dict) else str(site_obj) if site_obj else None
                        )
                        tenant_obj = data.get("tenant", {})
                        tenant = (
                            tenant_obj.get("name")
                            if isinstance(tenant_obj, dict)
                            else str(tenant_obj)
                            if tenant_obj
                            else None
                        )
                        primary_ip_obj = data.get("primary_ip", {})
                        primary_ip = (
                            primary_ip_obj.get("address")
                            if isinstance(primary_ip_obj, dict)
                            else str(primary_ip_obj)
                            if primary_ip_obj
                            else None
                        )
                        device_type_obj = data.get("device_type", {})
                        model = device_type_obj.get("model") if isinstance(device_type_obj, dict) else None
                        manufacturer_obj = (
                            device_type_obj.get("manufacturer", {}) if isinstance(device_type_obj, dict) else {}
                        )
                        manufacturer = manufacturer_obj.get("name") if isinstance(manufacturer_obj, dict) else None

                        results.append(
                            {
                                "type": "device",
                                "name": data.get("name") or getattr(device, "name", ""),
                                "id": data.get("id") or getattr(device, "id", 0),
                                "status": status_label,
                                "role": role,
                                "site": site,
                                "primary_ip": primary_ip,
                                "tenant": tenant,
                                "model": model,
                                "manufacturer": manufacturer,
                            }
                        )
                except Exception as e:
                    logger.warning(f"NetBox device search failed: {e}")

            def _search_vms():
                """Server-side VM search using NetBox API."""
                try:
                    raw_vms = list(client.api.virtualization.virtual_machines.filter(q=query_stripped, limit=limit))
                    for vm in raw_vms:
                        data = vm.serialize() if hasattr(vm, "serialize") else {}
                        status_obj = data.get("status", {})
                        status_label = (
                            status_obj.get("label")
                            if isinstance(status_obj, dict)
                            else str(status_obj)
                            if status_obj
                            else None
                        )
                        cluster_obj = data.get("cluster", {})
                        cluster = (
                            cluster_obj.get("name")
                            if isinstance(cluster_obj, dict)
                            else str(cluster_obj)
                            if cluster_obj
                            else None
                        )
                        site_obj = data.get("site", {})
                        site = (
                            site_obj.get("name") if isinstance(site_obj, dict) else str(site_obj) if site_obj else None
                        )
                        tenant_obj = data.get("tenant", {})
                        tenant = (
                            tenant_obj.get("name")
                            if isinstance(tenant_obj, dict)
                            else str(tenant_obj)
                            if tenant_obj
                            else None
                        )
                        primary_ip_obj = data.get("primary_ip", {})
                        primary_ip = (
                            primary_ip_obj.get("address")
                            if isinstance(primary_ip_obj, dict)
                            else str(primary_ip_obj)
                            if primary_ip_obj
                            else None
                        )
                        platform_obj = data.get("platform", {})
                        platform = (
                            platform_obj.get("name")
                            if isinstance(platform_obj, dict)
                            else str(platform_obj)
                            if platform_obj
                            else None
                        )

                        results.append(
                            {
                                "type": "vm",
                                "name": data.get("name") or getattr(vm, "name", ""),
                                "id": data.get("id") or getattr(vm, "id", 0),
                                "status": status_label,
                                "cluster": cluster,
                                "site": site,
                                "primary_ip": primary_ip,
                                "tenant": tenant,
                                "platform": platform,
                            }
                        )
                except Exception as e:
                    logger.warning(f"NetBox VM search failed: {e}")

            try:
                # Run device and VM searches in parallel
                await asyncio.gather(
                    asyncio.to_thread(_search_devices),
                    asyncio.to_thread(_search_vms),
                )
            except Exception as e:
                return f"## Error: NetBox Query Failed\n\n{e}"

            # Apply limit
            results = results[:limit]

            if not results:
                return f"## NetBox Search: {query}\n\nNo results found."

            output = f"## NetBox Search: {query}\n\n"
            output += f"*Found {len(results)} result(s)*\n\n"

            devices_found = [r for r in results if r["type"] == "device"]
            vms_found = [r for r in results if r["type"] == "vm"]

            if devices_found:
                output += "### Devices\n\n"
                for d in devices_found:
                    output += f"- **{d['name']}** (ID: {d['id']})\n"
                    output += f"  - Status: {d['status'] or 'N/A'} | Role: {d['role'] or 'N/A'}\n"
                    output += f"  - Site: {d['site'] or 'N/A'} | Tenant: {d['tenant'] or 'N/A'}\n"
                    output += f"  - IP: {d['primary_ip'] or 'N/A'}\n"
                    if d.get("manufacturer") or d.get("model"):
                        output += f"  - Hardware: {d['manufacturer'] or ''} {d['model'] or ''}\n"
                    output += "\n"

            if vms_found:
                output += "### Virtual Machines\n\n"
                for v in vms_found:
                    output += f"- **{v['name']}** (ID: {v['id']})\n"
                    output += f"  - Status: {v['status'] or 'N/A'} | Cluster: {v['cluster'] or 'N/A'}\n"
                    output += f"  - Site: {v['site'] or 'N/A'} | Tenant: {v['tenant'] or 'N/A'}\n"
                    output += f"  - IP: {v['primary_ip'] or 'N/A'}\n"
                    output += "\n"

            return output

        # =====================================================================
        # vCenter Tools
        # =====================================================================

        @self.server.tool()
        async def atlas_vcenter_list_instances() -> str:
            """
            List all configured vCenter instances with status.

            Returns:
                List of vCenter configurations with connection status
            """
            try:
                from infrastructure_atlas.application.services import create_vcenter_service
                from infrastructure_atlas.db import get_sessionmaker

                SessionLocal = get_sessionmaker()

                with SessionLocal() as db:
                    service = create_vcenter_service(db)
                    configs_with_meta = service.list_configs_with_status()

                    if not configs_with_meta:
                        return "## vCenter Instances\n\nNo vCenter instances configured."

                    output = "## vCenter Instances\n\n"
                    for config, meta in configs_with_meta:
                        name = config.name or config.base_url or config.id
                        output += f"### {name}\n"
                        output += f"- **ID**: `{config.id}`\n"
                        output += f"- **URL**: {config.base_url}\n"
                        output += f"- **Username**: {config.username}\n"

                        if meta:
                            output += f"- **VMs Cached**: {meta.get('vm_count', 'N/A')}\n"
                            output += f"- **Last Refresh**: {meta.get('generated_at', 'N/A')}\n"
                        else:
                            output += "- **Status**: No cached data\n"
                        output += "\n"

                    return output
            except Exception as e:
                return f"## Error: vCenter Query Failed\n\n{e}"

        @self.server.tool()
        async def atlas_vcenter_get_vms(config_id: str, limit: int = 20, search: str | None = None) -> str:
            """
            Get VMs from a specific vCenter instance.

            Args:
                config_id: The vCenter configuration ID
                limit: Maximum VMs to return (default 20, max 50)
                search: Optional search filter for VM name

            Returns:
                List of VMs with details
            """
            try:
                from infrastructure_atlas.application.services import create_vcenter_service
                from infrastructure_atlas.db import get_sessionmaker

                SessionLocal = get_sessionmaker()
                limit = min(limit, 50)

                with SessionLocal() as db:
                    service = create_vcenter_service(db)
                    config, vms, _meta = service.get_inventory(config_id, refresh=False)

                    if not vms:
                        return (
                            f"## vCenter VMs ({config.name or config_id})\n\nNo VMs found in cache. Run refresh first."
                        )

                    # Apply search filter
                    if search:
                        search_lower = search.lower()
                        vms = [vm for vm in vms if search_lower in (vm.name or "").lower()]

                    # Apply limit
                    total = len(vms)
                    vms = vms[:limit]

                    output = f"## vCenter VMs ({config.name or config_id})\n\n"
                    output += f"*Showing {len(vms)} of {total} VMs*\n\n"

                    for vm in vms:
                        power_icon = "🟢" if vm.power_state == "poweredOn" else "🔴"
                        output += f"### {power_icon} {vm.name}\n"
                        output += f"- **VM ID**: `{vm.vm_id}`\n"
                        output += f"- **Power State**: {vm.power_state}\n"
                        output += f"- **Guest OS**: {vm.guest_os or 'N/A'}\n"
                        output += f"- **CPU/Memory**: {vm.cpu_count or 'N/A'} vCPU / {vm.memory_mb or 'N/A'} MB\n"
                        output += f"- **Host**: {vm.host or 'N/A'}\n"
                        output += f"- **Cluster**: {vm.cluster or 'N/A'}\n"
                        if vm.guest_ip_address:
                            output += f"- **IP Address**: {vm.guest_ip_address}\n"
                        if vm.tools_status:
                            output += f"- **VMware Tools**: {vm.tools_status}\n"
                        output += "\n"

                    return output
            except Exception as e:
                return f"## Error: vCenter Query Failed\n\n{e}"

        # =====================================================================
        # Zabbix Tools
        # =====================================================================

        @self.server.tool()
        async def atlas_zabbix_alerts(
            min_severity: int = 0,
            unacknowledged_only: bool = False,
            limit: int = 50,
            search: str | None = None,
        ) -> str:
            """
            Get current Zabbix alerts (active problems).

            Args:
                min_severity: Minimum severity level (0-5, default 0)
                unacknowledged_only: Only show unacknowledged problems
                limit: Maximum alerts to return (default 50)
                search: Optional search filter for problem name or host

            Returns:
                Active Zabbix problems/alerts
            """
            try:
                client = _create_zabbix_client()
            except ValueError as e:
                return f"## Error: Zabbix Not Configured\n\n{e}"

            try:
                severities = list(range(min_severity, 6)) if min_severity > 0 else None

                problems = await asyncio.to_thread(
                    client.get_problems,
                    severities=severities,
                    unacknowledged=unacknowledged_only,
                    limit=limit,
                    search=search,
                )

                if not problems.items:
                    return "## Zabbix Alerts\n\nNo active problems found."

                output = "## Zabbix Alerts\n\n"
                output += f"*{len(problems.items)} active problem(s)*\n\n"

                for problem in problems.items:
                    sev_icon = ["⚪", "🔵", "🟡", "🟠", "🔴", "💥"][min(problem.severity, 5)]
                    ack_status = "✓" if problem.acknowledged else "✗"

                    output += f"### {sev_icon} {problem.name}\n"
                    output += f"- **Severity**: {_severity_label(problem.severity)}\n"
                    output += f"- **Host**: {problem.host_name or 'N/A'}\n"
                    output += f"- **Duration**: {problem.duration or 'N/A'}\n"
                    output += f"- **Acknowledged**: {ack_status}\n"
                    output += f"- **Started**: {problem.clock_iso}\n"

                    if problem.host_groups:
                        groups = ", ".join(g.name for g in problem.host_groups)
                        output += f"- **Groups**: {groups}\n"

                    if problem.problem_url:
                        output += f"- [View in Zabbix]({problem.problem_url})\n"

                    output += "\n"

                return output
            except Exception as e:
                return f"## Error: Zabbix Query Failed\n\n{e}"

        # =====================================================================
        # Jira Tools
        # =====================================================================

        @self.server.tool()
        async def atlas_jira_search(
            jql: str | None = None,
            query: str | None = None,
            project: str | None = None,
            max_results: int = 20,
        ) -> str:
            """
            Search Jira issues.

            Args:
                jql: Explicit JQL query (overrides other filters)
                query: Free-text search across summary, description, comments
                project: Filter by project key
                max_results: Maximum issues to return (default 20)

            Returns:
                Matching Jira issues
            """
            import requests

            try:
                base_url = os.getenv("ATLASSIAN_BASE_URL", "").strip()
                email = os.getenv("ATLASSIAN_EMAIL", "").strip()
                api_token = os.getenv("ATLASSIAN_API_TOKEN", "").strip()

                if not (base_url and email and api_token):
                    return (
                        "## Error: Jira Not Configured\n\nSet ATLASSIAN_BASE_URL, ATLASSIAN_EMAIL, ATLASSIAN_API_TOKEN"
                    )

                sess = requests.Session()
                sess.auth = (email, api_token)
                sess.headers.update({"Accept": "application/json"})
                base = base_url.rstrip("/")

                # Build JQL
                if jql:
                    jql_str = jql.strip()
                else:
                    parts = []
                    if project:
                        parts.append(f"project = {project}")
                    if query:
                        qq = query.replace('"', '\\"')
                        parts.append(f'text ~ "{qq}"')
                    if not parts:
                        parts.append("updated >= -30d")
                    jql_str = " AND ".join(parts) + " ORDER BY updated DESC"

                # Execute search
                url = f"{base}/rest/api/3/search/jql"
                params = {
                    "jql": jql_str,
                    "maxResults": min(max_results, 50),
                    "fields": "key,summary,status,assignee,priority,updated,created,issuetype,project",
                }

                response = await asyncio.to_thread(sess.get, url, params=params, timeout=60)

                if response.status_code == 401:
                    return "## Error: Jira Authentication Failed\n\nCheck ATLASSIAN_EMAIL and ATLASSIAN_API_TOKEN"
                response.raise_for_status()

                data = response.json()
                issues = data.get("issues", [])

                if not issues:
                    return f"## Jira Search\n\n**JQL**: `{jql_str}`\n\nNo issues found."

                output = f"## Jira Search\n\n**JQL**: `{jql_str}`\n\n"
                output += f"*Found {data.get('total', len(issues))} issue(s)*\n\n"

                for issue in issues:
                    key = issue.get("key", "")
                    fields = issue.get("fields", {})
                    summary = fields.get("summary", "")
                    status = (fields.get("status") or {}).get("name", "")
                    assignee = (fields.get("assignee") or {}).get("displayName", "Unassigned")
                    priority = (fields.get("priority") or {}).get("name", "")
                    issue_type = (fields.get("issuetype") or {}).get("name", "")
                    updated = fields.get("updated", "")[:10]

                    output += f"### [{key}]({base}/browse/{key})\n"
                    output += f"**{summary}**\n\n"
                    output += f"- Type: {issue_type} | Status: {status} | Priority: {priority}\n"
                    output += f"- Assignee: {assignee} | Updated: {updated}\n\n"

                return output
            except Exception as e:
                return f"## Error: Jira Query Failed\n\n{e}"

        @self.server.tool()
        async def atlas_jira_get_remote_links(issue_key: str) -> str:
            """
            Get remote links for a Jira issue.

            Args:
                issue_key: The Jira issue key (e.g., "ESD-123")

            Returns:
                List of remote links on the issue
            """
            import requests

            try:
                base_url = os.getenv("ATLASSIAN_BASE_URL", "").strip()
                email = os.getenv("ATLASSIAN_EMAIL", "").strip()
                api_token = os.getenv("ATLASSIAN_API_TOKEN", "").strip()

                if not (base_url and email and api_token):
                    return (
                        "## Error: Jira Not Configured\n\nSet ATLASSIAN_BASE_URL, ATLASSIAN_EMAIL, ATLASSIAN_API_TOKEN"
                    )

                sess = requests.Session()
                sess.auth = (email, api_token)
                sess.headers.update({"Accept": "application/json"})
                base = base_url.rstrip("/")

                url = f"{base}/rest/api/3/issue/{issue_key}/remotelink"
                response = await asyncio.to_thread(sess.get, url, timeout=30)

                if response.status_code == 404:
                    return f"## Error\n\nIssue {issue_key} not found"
                response.raise_for_status()

                links = response.json()

                if not links:
                    return f"## Remote Links: {issue_key}\n\nNo remote links found."

                output = f"## Remote Links: {issue_key}\n\n"
                for link in links:
                    link_id = link.get("id")
                    obj = link.get("object", {})
                    title = obj.get("title", "Untitled")
                    url = obj.get("url", "")
                    relationship = link.get("relationship", "")

                    output += f"- **{title}**\n"
                    output += f"  - URL: {url}\n"
                    output += f"  - Relationship: {relationship}\n"
                    output += f"  - Link ID: {link_id}\n\n"

                return output
            except Exception as e:
                return f"## Error: Failed to get remote links\n\n{e}"

        @self.server.tool()
        async def atlas_jira_create_confluence_link(
            issue_key: str, confluence_page_id: str, title: str | None = None, relationship: str = "Wiki Page"
        ) -> str:
            """
            Create a remote link from a Jira issue to a Confluence page.

            Args:
                issue_key: The Jira issue key (e.g., "ESD-123")
                confluence_page_id: The Confluence page ID
                title: Optional link title (defaults to "Confluence Page {page_id}")
                relationship: Relationship type (default "Wiki Page")

            Returns:
                Success/failure status
            """
            import requests

            try:
                base_url = os.getenv("ATLASSIAN_BASE_URL", "").strip()
                email = os.getenv("ATLASSIAN_EMAIL", "").strip()
                api_token = os.getenv("ATLASSIAN_API_TOKEN", "").strip()

                if not (base_url and email and api_token):
                    return (
                        "## Error: Jira Not Configured\n\nSet ATLASSIAN_BASE_URL, ATLASSIAN_EMAIL, ATLASSIAN_API_TOKEN"
                    )

                sess = requests.Session()
                sess.auth = (email, api_token)
                sess.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
                base = base_url.rstrip("/")

                # Confluence remote link configuration
                APP_ID = "c040a8bc-dafc-3073-aee9-8b0b4ba30eb0"
                APP_NAME = "System Confluence"

                global_id = f"appId={APP_ID}&pageId={confluence_page_id}"
                page_url = f"{base}/wiki/pages/viewpage.action?pageId={confluence_page_id}"
                link_title = title or f"Confluence Page {confluence_page_id}"

                payload = {
                    "globalId": global_id,
                    "application": {"type": "com.atlassian.confluence", "name": APP_NAME},
                    "relationship": relationship,
                    "object": {
                        "url": page_url,
                        "title": link_title,
                        "icon": {"url16x16": f"{base}/wiki/favicon.ico", "title": "Confluence"},
                    },
                }

                url = f"{base}/rest/api/3/issue/{issue_key}/remotelink"
                response = await asyncio.to_thread(sess.post, url, json=payload, timeout=30)

                if response.status_code == 404:
                    return f"## Error\n\nIssue {issue_key} not found"
                response.raise_for_status()

                result = response.json()

                return f"""## Remote Link Created

- **Issue**: {issue_key}
- **Title**: {link_title}
- **Page URL**: {page_url}
- **Link ID**: {result.get("id")}
"""
            except Exception as e:
                return f"## Error: Failed to create remote link\n\n{e}"

        @self.server.tool()
        async def atlas_jira_delete_remote_link(issue_key: str, link_id: str) -> str:
            """
            Delete a remote link from a Jira issue.

            Args:
                issue_key: The Jira issue key (e.g., "ESD-123")
                link_id: The remote link ID to delete

            Returns:
                Success/failure status
            """
            import requests

            try:
                base_url = os.getenv("ATLASSIAN_BASE_URL", "").strip()
                email = os.getenv("ATLASSIAN_EMAIL", "").strip()
                api_token = os.getenv("ATLASSIAN_API_TOKEN", "").strip()

                if not (base_url and email and api_token):
                    return (
                        "## Error: Jira Not Configured\n\nSet ATLASSIAN_BASE_URL, ATLASSIAN_EMAIL, ATLASSIAN_API_TOKEN"
                    )

                sess = requests.Session()
                sess.auth = (email, api_token)
                sess.headers.update({"Accept": "application/json"})
                base = base_url.rstrip("/")

                url = f"{base}/rest/api/3/issue/{issue_key}/remotelink/{link_id}"
                response = await asyncio.to_thread(sess.delete, url, timeout=30)

                if response.status_code == 404:
                    return "## Error\n\nLink or issue not found"
                response.raise_for_status()

                return f"## Remote Link Deleted\n\n- **Issue**: {issue_key}\n- **Link ID**: {link_id}"
            except Exception as e:
                return f"## Error: Failed to delete remote link\n\n{e}"

        # Register Jira attachment tools (from original MCP server)
        self._register_jira_attachment_tools()

        # =====================================================================
        # Confluence Search Tool (basic CQL, not RAG)
        # =====================================================================

        @self.server.tool()
        async def atlas_confluence_search(
            cql: str | None = None,
            query: str | None = None,
            space: str | None = None,
            max_results: int = 20,
        ) -> str:
            """
            Search Confluence pages using CQL.

            For semantic search with citations, use search_confluence_docs instead.

            Args:
                cql: Explicit CQL query (overrides other filters)
                query: Free-text search
                space: Filter by space key
                max_results: Maximum results to return (default 20)

            Returns:
                Matching Confluence pages
            """
            import requests

            try:
                base_url = os.getenv("ATLASSIAN_BASE_URL", "").strip()
                email = os.getenv("ATLASSIAN_EMAIL", "").strip()
                api_token = os.getenv("ATLASSIAN_API_TOKEN", "").strip()

                if not (base_url and email and api_token):
                    return "## Error: Confluence Not Configured\n\nSet ATLASSIAN_BASE_URL, ATLASSIAN_EMAIL, ATLASSIAN_API_TOKEN"

                sess = requests.Session()
                sess.auth = (email, api_token)
                sess.headers.update({"Accept": "application/json"})
                base = base_url.rstrip("/")

                # Build CQL
                if cql:
                    cql_str = cql.strip()
                else:
                    parts = ["type = page"]
                    if space:
                        parts.append(f"space = {space}")
                    if query:
                        qq = query.replace('"', '\\"')
                        parts.append(f'text ~ "{qq}"')
                    cql_str = " AND ".join(parts) + " ORDER BY lastModified DESC"

                url = f"{base}/wiki/rest/api/content/search"
                params = {"cql": cql_str, "limit": min(max_results, 50)}

                response = await asyncio.to_thread(sess.get, url, params=params, timeout=60)

                if response.status_code == 401:
                    return "## Error: Confluence Authentication Failed\n\nCheck ATLASSIAN_EMAIL and ATLASSIAN_API_TOKEN"
                response.raise_for_status()

                data = response.json()
                results = data.get("results", [])

                if not results:
                    return f"## Confluence Search\n\n**CQL**: `{cql_str}`\n\nNo results found."

                output = f"## Confluence Search\n\n**CQL**: `{cql_str}`\n\n"
                output += f"*Found {data.get('totalSize', len(results))} result(s)*\n\n"

                for page in results:
                    title = page.get("title", "Untitled")
                    page_id = page.get("id", "")
                    space_info = page.get("space", {})
                    space_key = space_info.get("key", "")

                    links = page.get("_links", {})
                    web_ui = links.get("webui", "")
                    page_url = f"{base}/wiki{web_ui}" if web_ui else ""

                    output += f"### [{title}]({page_url})\n"
                    output += f"- Space: {space_key} | Page ID: {page_id}\n\n"

                return output
            except Exception as e:
                return f"## Error: Confluence Query Failed\n\n{e}"

        # =====================================================================
        # Commvault Tools
        # =====================================================================

        @self.server.tool()
        async def atlas_commvault_info(hostname: str, hours: int = 24, limit: int = 10) -> str:
            """
            Get Commvault backup status and job history for a hostname.

            Args:
                hostname: Target hostname or client name to search
                hours: Hours of history to look back (default 24)
                limit: Maximum jobs to return (default 10)

            Returns:
                Backup jobs and status for the hostname
            """
            try:
                client = _create_commvault_client()
            except ValueError as e:
                return f"## Error: Commvault Not Configured\n\n{e}"

            try:
                # List clients and find matching ones
                clients = await asyncio.to_thread(client.list_clients, limit=500)
                hostname_lower = hostname.lower()

                matching_clients = [c for c in clients if hostname_lower in (c.name or "").lower()]

                if not matching_clients:
                    # Try VMs as well
                    vms = await asyncio.to_thread(client.list_virtual_machines, limit=500)
                    matching_clients = [v for v in vms if hostname_lower in (v.name or "").lower()]

                if not matching_clients:
                    return f"## Commvault: {hostname}\n\nNo matching clients or VMs found."

                output = f"## Commvault Backup Status: {hostname}\n\n"

                from datetime import timedelta

                from infrastructure_atlas.infrastructure.external import CommvaultJobQuery

                since = datetime.now(tz=UTC) - timedelta(hours=hours)

                for matched in matching_clients[:3]:  # Limit to first 3 matches
                    output += f"### {matched.name}\n"
                    output += f"- **Client ID**: {matched.client_id}\n"

                    # Get job history
                    try:
                        query = CommvaultJobQuery(limit=limit, since=since, descending=True)
                        summary = await asyncio.to_thread(client.get_client_summary, matched.client_id, job_query=query)

                        if summary.job_metrics and summary.job_metrics.jobs:
                            output += f"- **Jobs in last {hours}h**: {len(summary.job_metrics.jobs)}\n\n"

                            output += "| Status | Type | Start | Size |\n"
                            output += "|--------|------|-------|------|\n"

                            for job in summary.job_metrics.jobs[:limit]:
                                start = _format_datetime(job.start_time)
                                size = _format_size(job.size_of_application_bytes or 0)
                                output += (
                                    f"| {job.status} | {job.backup_level_name or job.job_type} | {start} | {size} |\n"
                                )

                            output += "\n"
                        else:
                            output += f"- No jobs found in last {hours} hours\n\n"

                    except Exception as e:
                        output += f"- Error fetching jobs: {e}\n\n"

                return output
            except Exception as e:
                return f"## Error: Commvault Query Failed\n\n{e}"

        # =====================================================================
        # Unified Cross-System Search
        # =====================================================================

        @self.server.tool()
        async def atlas_search(query: str, limit: int = 10) -> str:
            """
            Search across all Atlas systems (NetBox, vCenter, Zabbix, Jira, Confluence, Commvault).

            This is a unified search that queries all configured systems in PARALLEL.

            Args:
                query: Search query (hostname, IP, ticket ID, etc.)
                limit: Maximum results per system (default 10)

            Returns:
                Combined search results from all systems
            """
            output = f"## Unified Atlas Search: {query}\n\n"
            sections: list[tuple[str, str]] = []

            # Define search tasks that will run in parallel
            async def search_netbox():
                try:
                    result = await atlas_netbox_search(query, limit=limit)
                    if "No results found" not in result and "Error" not in result:
                        return ("NetBox", result.split("\n\n", 1)[1] if "\n\n" in result else result)
                except Exception as e:
                    return ("NetBox", f"*Error: {e}*")
                return None

            async def search_vcenter():
                try:
                    from infrastructure_atlas.application.services import create_vcenter_service
                    from infrastructure_atlas.db import get_sessionmaker

                    def _search():
                        SessionLocal = get_sessionmaker()
                        vcenter_results = []
                        with SessionLocal() as db:
                            service = create_vcenter_service(db)
                            configs_with_meta = service.list_configs_with_status()
                            query_lower = query.lower()

                            for config, _ in configs_with_meta:
                                try:
                                    _, vms, _ = service.get_inventory(config.id, refresh=False)
                                    for vm in vms:
                                        searchable = " ".join(
                                            filter(
                                                None,
                                                [
                                                    vm.name,
                                                    vm.guest_ip_address,
                                                    vm.guest_host_name,
                                                    *list(vm.ip_addresses or []),
                                                ],
                                            )
                                        ).lower()
                                        if query_lower in searchable:
                                            vcenter_results.append(
                                                f"- **{vm.name}** ({vm.power_state}) - {config.name or config.id}"
                                            )
                                            if len(vcenter_results) >= limit:
                                                break
                                except Exception:
                                    pass
                                if len(vcenter_results) >= limit:
                                    break
                        return vcenter_results

                    vcenter_results = await asyncio.to_thread(_search)
                    if vcenter_results:
                        return ("vCenter", "\n".join(vcenter_results))
                except Exception as e:
                    return ("vCenter", f"*Error: {e}*")
                return None

            async def search_zabbix():
                try:
                    result = await atlas_zabbix_alerts(search=query, limit=limit)
                    if "No active problems" not in result and "Error" not in result:
                        return ("Zabbix", result.split("\n\n", 1)[1] if "\n\n" in result else result)
                except Exception as e:
                    return ("Zabbix", f"*Error: {e}*")
                return None

            async def search_jira():
                try:
                    result = await atlas_jira_search(query=query, max_results=limit)
                    if "No issues found" not in result and "Error" not in result:
                        return ("Jira", result.split("\n\n", 2)[2] if result.count("\n\n") >= 2 else result)
                except Exception as e:
                    return ("Jira", f"*Error: {e}*")
                return None

            async def search_confluence():
                try:
                    result = await atlas_confluence_search(query=query, max_results=limit)
                    if "No results found" not in result and "Error" not in result:
                        return ("Confluence", result.split("\n\n", 2)[2] if result.count("\n\n") >= 2 else result)
                except Exception as e:
                    return ("Confluence", f"*Error: {e}*")
                return None

            # Run all searches in parallel
            results = await asyncio.gather(
                search_netbox(),
                search_vcenter(),
                search_zabbix(),
                search_jira(),
                search_confluence(),
                return_exceptions=True,
            )

            # Collect non-None results
            for result in results:
                if isinstance(result, Exception):
                    continue
                if result is not None:
                    sections.append(result)

            # Build output
            if not sections:
                output += "*No results found in any system.*"
            else:
                for system, content in sections:
                    output += f"### {system}\n\n{content}\n\n---\n\n"

            return output

    def _register_confluence_rag_tools(self):
        """Register Confluence RAG search tools."""

        @self.server.tool()
        async def search_confluence_docs(
            query: str, top_k: int = 5, include_citations: bool = True, spaces: list[str] | None = None
        ) -> str:
            """
            Search Confluence documentation with semantic search.

            Returns relevant passages with exact citations and source references.
            Use this for finding procedures, troubleshooting guides,
            and technical documentation.
            """
            config = SearchConfig(top_k=top_k, include_citations=include_citations)
            response = await self.search.search(query, config)
            return self._format_search_results(response)

        @self.server.tool()
        async def get_confluence_page(
            page_id: str | None = None, page_title: str | None = None, space_key: str | None = None
        ) -> str:
            """
            Retrieve a specific Confluence page from RAG cache.
            Provide either page_id OR (page_title + space_key).
            """
            conn = self.db.connect()

            if page_id:
                page = conn.execute("SELECT * FROM pages WHERE page_id = $1", [page_id]).fetchone()
            elif page_title and space_key:
                page = conn.execute(
                    "SELECT * FROM pages WHERE title ILIKE $1 AND space_key = $2", [f"%{page_title}%", space_key]
                ).fetchone()
            else:
                return "Error: Provide either page_id or (page_title + space_key)"

            if not page:
                return "Page not found"

            columns = [desc[0] for desc in conn.description]
            page_dict = dict(zip(columns, page))

            chunks = conn.execute(
                "SELECT content, heading_context FROM chunks WHERE page_id = $1 ORDER BY position_in_page",
                [page_dict["page_id"]],
            ).fetchall()

            return self._format_page(page_dict, chunks)

        @self.server.tool()
        async def list_confluence_spaces() -> str:
            """List available Confluence spaces in the RAG cache."""
            conn = self.db.connect()

            spaces = conn.execute(
                """
                SELECT
                    space_key,
                    COUNT(*) as page_count,
                    MAX(synced_at) as last_sync
                FROM pages
                GROUP BY space_key
                ORDER BY space_key
            """
            ).fetchall()

            result = "## Available Confluence Spaces\n\n"
            for space in spaces:
                result += f"- **{space[0]}**: {space[1]} pages (sync: {space[2]})\n"

            return result

        @self.server.tool()
        async def get_confluence_stats() -> str:
            """Get statistics about the Confluence RAG cache."""
            conn = self.db.connect()

            try:
                stats = conn.execute(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM pages) as total_pages,
                        (SELECT COUNT(*) FROM chunks) as total_chunks,
                        (SELECT COUNT(*) FROM chunk_embeddings) as total_embeddings,
                        (SELECT MAX(synced_at) FROM pages) as last_sync
                """
                ).fetchone()

                result = "## Confluence RAG Cache Statistics\n\n"
                result += f"- **Total Pages**: {stats[0]}\n"
                result += f"- **Total Chunks**: {stats[1]}\n"
                result += f"- **Total Embeddings**: {stats[2]}\n"
                result += f"- **Last Sync**: {stats[3]}\n"

                return result
            except Exception:
                return "Cache empty or not initialized"

        @self.server.tool()
        async def generate_guide_from_docs(query: str, max_pages: int = 5) -> str:
            """
            Search documentation and return FULL content from cached pages.

            Use this to generate comprehensive guides from internal documentation.
            Returns complete page content (not just snippets).

            Args:
                query: What to search for (e.g., "configure MS Defender", "CEPH tenants")
                max_pages: Maximum number of relevant pages to include (default 5)
            """
            config = SearchConfig(top_k=max_pages * 3, include_citations=False)
            response = await self.search.search(query, config)

            if not response.results:
                return f"No documentation found for: {query}"

            conn = self.db.connect()
            seen_pages = set()
            pages_content = []

            for result in response.results:
                page_id = result.page.page_id
                if page_id in seen_pages:
                    continue
                seen_pages.add(page_id)

                if len(seen_pages) > max_pages:
                    break

                chunks = conn.execute(
                    """
                    SELECT content, heading_context
                    FROM chunks
                    WHERE page_id = $1
                    ORDER BY position_in_page
                """,
                    [page_id],
                ).fetchall()

                page_content = self._format_page_for_guide(result.page, chunks)
                pages_content.append(page_content)

            output = f"# Documentation: {query}\n\n"
            output += f"*Found {len(pages_content)} relevant pages from internal documentation*\n\n"
            output += "---\n\n"

            for content in pages_content:
                output += content
                output += "\n---\n\n"

            return output

        @self.server.tool()
        async def get_doc_content(page_title: str) -> str:
            """
            Get full content of a documentation page by title (from RAG cache).

            Use this when you know the exact page title and want full content.
            """
            conn = self.db.connect()

            page = conn.execute("SELECT * FROM pages WHERE title ILIKE $1 LIMIT 1", [f"%{page_title}%"]).fetchone()

            if not page:
                words = page_title.split()
                if len(words) > 1:
                    pattern = "%" + "%".join(words) + "%"
                    page = conn.execute("SELECT * FROM pages WHERE title ILIKE $1 LIMIT 1", [pattern]).fetchone()

            if not page:
                return f"Page not found: {page_title}"

            columns = [desc[0] for desc in conn.description]
            page_dict = dict(zip(columns, page))

            chunks = conn.execute(
                "SELECT content, heading_context FROM chunks WHERE page_id = $1 ORDER BY position_in_page",
                [page_dict["page_id"]],
            ).fetchall()

            return self._format_page(page_dict, chunks)

    def _register_jira_attachment_tools(self):
        """Register Jira attachment tools."""
        from infrastructure_atlas.infrastructure.external.jira_client import (
            JiraAPIError,
            JiraConfigError,
            create_jira_client_from_env,
        )

        @self.server.tool()
        async def atlas_jira_attach_file(
            issue_id_or_key: str,
            file_url: str,
            filename: str | None = None,
        ) -> str:
            """
            Download a file from a URL and attach it to a Jira issue.

            Use this to preserve attachments from external links (like Equinix power reports)
            by downloading and attaching them directly to tickets.

            Args:
                issue_id_or_key: The Jira issue key (e.g., "ESD-40185") or numeric ID
                file_url: URL to download the file from (must be publicly accessible)
                filename: Optional filename override

            Returns:
                Success/failure status with attachment metadata
            """
            try:
                jira_client = create_jira_client_from_env()
            except JiraConfigError as e:
                return f"## Error: Jira Not Configured\n\n{e}\n\nSet ATLASSIAN_BASE_URL, ATLASSIAN_EMAIL, ATLASSIAN_API_TOKEN environment variables."

            try:
                attachment = await jira_client.download_and_upload_attachment_async(
                    issue_id_or_key=issue_id_or_key,
                    source_url=file_url,
                    filename=filename,
                )

                return f"""## Attachment Uploaded Successfully

- **Issue**: {issue_id_or_key}
- **Filename**: {attachment.filename}
- **Size**: {_format_size(attachment.size)}
- **MIME Type**: {attachment.mime_type or "unknown"}
- **Attachment ID**: {attachment.id}
- **Download URL**: {attachment.content_url or "N/A"}
"""
            except JiraAPIError as e:
                return f"## Error: Upload Failed\n\n{e}"
            except Exception as e:
                logger.exception("Unexpected error in atlas_jira_attach_file")
                return f"## Error: Unexpected Failure\n\n{e}"
            finally:
                jira_client.close()

        @self.server.tool()
        async def atlas_jira_attach_files(
            issue_id_or_key: str,
            files: list[dict],
        ) -> str:
            """
            Download multiple files from URLs and attach them to a Jira issue (batch operation).

            Args:
                issue_id_or_key: The Jira issue key (e.g., "ESD-40185") or numeric ID
                files: List of file objects, each with:
                    - url: URL to download the file from
                    - filename: Optional filename override

            Returns:
                Summary of upload results for each file
            """
            try:
                jira_client = create_jira_client_from_env()
            except JiraConfigError as e:
                return f"## Error: Jira Not Configured\n\n{e}"

            results = []
            success_count = 0
            error_count = 0

            try:
                for file_entry in files:
                    url = file_entry.get("url")
                    fname = file_entry.get("filename")

                    if not url:
                        results.append("- **Skipped**: Missing URL in entry")
                        error_count += 1
                        continue

                    try:
                        attachment = await jira_client.download_and_upload_attachment_async(
                            issue_id_or_key=issue_id_or_key,
                            source_url=url,
                            filename=fname,
                        )
                        results.append(
                            f"- **{attachment.filename}**: Uploaded ({_format_size(attachment.size)}, ID: {attachment.id})"
                        )
                        success_count += 1
                    except Exception as e:
                        results.append(f"- **{fname or url[:50]}...**: Failed - {e}")
                        error_count += 1

                status = (
                    "All files uploaded" if error_count == 0 else f"{success_count} succeeded, {error_count} failed"
                )
                return f"""## Batch Upload Results

**Issue**: {issue_id_or_key}
**Status**: {status}

### Files:
{chr(10).join(results)}
"""
            finally:
                jira_client.close()

        @self.server.tool()
        async def atlas_jira_list_attachments(issue_id_or_key: str) -> str:
            """
            List all attachments on a Jira issue.

            Args:
                issue_id_or_key: The Jira issue key (e.g., "ESD-40185") or numeric ID

            Returns:
                List of attachments with metadata
            """
            try:
                jira_client = create_jira_client_from_env()
            except JiraConfigError as e:
                return f"## Error: Jira Not Configured\n\n{e}"

            try:
                attachments = await asyncio.to_thread(jira_client.list_attachments, issue_id_or_key)

                if not attachments:
                    return f"## Attachments for {issue_id_or_key}\n\nNo attachments found."

                lines = [f"## Attachments for {issue_id_or_key}\n"]
                lines.append(f"*{len(attachments)} attachment(s)*\n")

                for att in attachments:
                    created = att.created_at.strftime("%Y-%m-%d %H:%M") if att.created_at else "unknown"
                    lines.append(f"- **{att.filename}** ({_format_size(att.size)})")
                    lines.append(f"  - Type: {att.mime_type or 'unknown'}")
                    lines.append(f"  - Created: {created}")
                    lines.append(f"  - ID: {att.id}")
                    if att.content_url:
                        lines.append(f"  - [Download]({att.content_url})")
                    lines.append("")

                return "\n".join(lines)
            except JiraAPIError as e:
                return f"## Error\n\n{e}"
            finally:
                jira_client.close()

    def _format_search_results(self, response: SearchResponse) -> str:
        """Format search results for Claude output."""
        output = f'## Search Results for: "{response.query}"\n\n'
        output += f"*{response.total_results} results in {response.search_time_ms:.0f}ms*\n\n"

        for i, result in enumerate(response.results, 1):
            output += f"### {i}. {result.page.title}\n"
            output += f"**Space:** {result.page.space_key} | "
            output += f"**Section:** {' > '.join(result.context_path)}\n"
            output += f"**Relevance:** {result.relevance_score:.2%}\n\n"

            output += f"{result.content[:300]}{'...' if len(result.content) > 300 else ''}\n\n"

            if result.citations:
                output += "**Citations:**\n"
                for citation in result.citations:
                    output += f'> "{citation.quote}"\n'
                    output += f"> - [{citation.page_title}]({citation.page_url})"
                    if citation.section:
                        output += f" - {citation.section}"
                    output += f" (confidence: {citation.confidence_score:.0%})\n\n"

            output += f"[Open in Confluence]({result.page.url})\n\n"
            output += "---\n\n"

        return output

    def _format_page(self, page: dict, chunks: list) -> str:
        """Format a page for output."""
        output = f"# {page['title']}\n\n"
        output += f"**Space:** {page['space_key']} | "
        output += f"**Updated:** {page['updated_at']} by {page['updated_by']}\n"
        output += f"**URL:** {page['url']}\n\n"
        output += "---\n\n"

        current_heading = None
        for chunk in chunks:
            if chunk[1] != current_heading:
                current_heading = chunk[1]
                if current_heading:
                    output += f"## {current_heading}\n\n"
            output += f"{chunk[0]}\n\n"

        return output

    def _format_page_for_guide(self, page, chunks: list) -> str:
        """Format a page for guide output."""
        output = f"## {page.title}\n\n"
        output += f"*Source: {page.space_key} - Updated: {page.updated_at}*\n\n"

        current_heading = None
        for chunk in chunks:
            if chunk[1] != current_heading:
                current_heading = chunk[1]
                if current_heading:
                    output += f"### {current_heading}\n\n"
            output += f"{chunk[0]}\n\n"

        return output

    async def run(self):
        """Start the MCP server."""
        await self.server.run_stdio_async()


# =============================================================================
# Legacy Compatibility - AtlasConfluenceMCPServer alias
# =============================================================================

# For backwards compatibility with run_mcp.py
AtlasConfluenceMCPServer = AtlasMCPServer
