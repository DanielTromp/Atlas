"""Tool definitions for AI chat agents.

This module defines tools that the AI can use to interact with Atlas systems.
Tools are defined in OpenAI function calling format for compatibility.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class ToolDefinition:
    """Definition of a tool that can be called by the AI."""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Any] | None = None
    category: str = "general"
    requires_auth: bool = False

    def to_openai_format(self) -> dict[str, Any]:
        """Convert to OpenAI function calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


# Core Atlas tool definitions
ATLAS_TOOLS: list[ToolDefinition] = [
    # NetBox tools
    ToolDefinition(
        name="netbox_search",
        description="Search NetBox inventory for devices, VMs, IP addresses, or other infrastructure components. Use this to find information about servers, network devices, and virtual machines.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (hostname, IP, device name, etc.)",
                },
                "dataset": {
                    "type": "string",
                    "enum": ["all", "devices", "vms"],
                    "description": "Dataset to search: all, devices only, or VMs only",
                    "default": "all",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return",
                    "default": 25,
                },
            },
            "required": ["query"],
        },
        category="inventory",
    ),
    # Zabbix tools
    ToolDefinition(
        name="zabbix_alerts",
        description="Get current Zabbix monitoring alerts and problems. Returns alerts with host groups and duration. Use this to check for active issues, outages, or performance problems.",
        parameters={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of alerts to return",
                    "default": 50,
                },
                "severities": {
                    "type": "string",
                    "description": "Comma-separated severity levels (1=info, 2=warning, 3=average, 4=high, 5=disaster)",
                },
                "group_ids": {
                    "type": "string",
                    "description": "Comma-separated host group IDs to filter by",
                },
                "unacknowledged_only": {
                    "type": "boolean",
                    "description": "Only show unacknowledged alerts",
                    "default": False,
                },
                "include_subgroups": {
                    "type": "boolean",
                    "description": "Include alerts from subgroups when filtering by group IDs",
                    "default": True,
                },
            },
        },
        category="monitoring",
    ),
    ToolDefinition(
        name="zabbix_host_search",
        description="Search for Zabbix hosts by name or group. Use this to find host IDs and information.",
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Host name or pattern to search for",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results",
                    "default": 20,
                },
            },
            "required": ["name"],
        },
        category="monitoring",
    ),
    ToolDefinition(
        name="zabbix_group_search",
        description="Search for Zabbix host groups by name. Use this to find group IDs before filtering alerts by group.",
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Group name or pattern to search for (use * for wildcards)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results",
                    "default": 50,
                },
            },
            "required": ["name"],
        },
        category="monitoring",
    ),
    # Jira tools
    ToolDefinition(
        name="jira_search",
        description="Search Jira issues. Use this to find tickets, incidents, or tasks related to infrastructure.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query text (searches summary, description)",
                },
                "project": {
                    "type": "string",
                    "description": "Project key to filter by (e.g., 'SYS', 'OPS')",
                },
                "status": {
                    "type": "string",
                    "description": "Status filter (e.g., 'Open', 'In Progress', 'Done')",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results",
                    "default": 20,
                },
            },
        },
        category="issues",
    ),
    # Confluence tools
    ToolDefinition(
        name="search_confluence_docs",
        description="""Search Confluence documentation using semantic/AI-powered search. This is the PRIMARY tool for finding documentation, runbooks, procedures, and how-to guides.

ALWAYS use this tool first when the user asks about:
- How to do something (procedures, guides)
- Documentation or runbooks
- Troubleshooting steps
- Configuration instructions
- Best practices

Returns relevant document excerpts with citations and source links.""",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search query describing what you're looking for",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results to return (default: 5, max: 20)",
                    "default": 5,
                },
                "spaces": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of space keys to limit search to",
                },
            },
            "required": ["query"],
        },
        category="documentation",
    ),
    ToolDefinition(
        name="confluence_search",
        description="Basic keyword search of Confluence pages. Use search_confluence_docs instead for better semantic search results.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query",
                },
                "space": {
                    "type": "string",
                    "description": "Confluence space key or name to search in",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results",
                    "default": 25,
                },
            },
            "required": ["query"],
        },
        category="documentation",
    ),
    # vCenter tools
    ToolDefinition(
        name="vcenter_list_instances",
        description="List all configured vCenter instances with their status and VM counts.",
        parameters={
            "type": "object",
            "properties": {},
        },
        category="virtualization",
    ),
    ToolDefinition(
        name="vcenter_get_vms",
        description="Get virtual machines from a specific vCenter instance.",
        parameters={
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
        category="virtualization",
    ),
    # Aggregate search
    ToolDefinition(
        name="search_aggregate",
        description="Search across all Atlas systems simultaneously (Zabbix, Jira, Confluence, vCenter, NetBox). Use this for comprehensive troubleshooting and finding all information about a server or component.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (hostname, VM name, IP address, or keyword)",
                },
                "zlimit": {
                    "type": "integer",
                    "description": "Max Zabbix results (0 = unlimited)",
                    "default": 10,
                },
                "jlimit": {
                    "type": "integer",
                    "description": "Max Jira results (0 = unlimited)",
                    "default": 10,
                },
                "climit": {
                    "type": "integer",
                    "description": "Max Confluence results (0 = unlimited)",
                    "default": 10,
                },
                "vlimit": {
                    "type": "integer",
                    "description": "Max vCenter results (0 = unlimited)",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
        category="search",
    ),
    # Ticket management tools
    ToolDefinition(
        name="ticket_list",
        description="List all tickets in the staging area. Use this to see pending ticket proposals, their status, and counts.",
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["proposed", "approved", "pushed", "rejected"],
                    "description": "Filter by ticket status",
                },
            },
        },
        category="tickets",
    ),
    ToolDefinition(
        name="ticket_create",
        description="Create a new ticket proposal. Use this to suggest infrastructure changes, report issues, or propose improvements.",
        parameters={
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Ticket title (required)",
                },
                "description": {
                    "type": "string",
                    "description": "Detailed ticket description",
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "critical"],
                    "description": "Priority level",
                    "default": "medium",
                },
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Labels/tags for the ticket",
                },
                "linked_jira_key": {
                    "type": "string",
                    "description": "Related Jira issue key (e.g., INFRA-123)",
                },
                "rationale": {
                    "type": "string",
                    "description": "Your reasoning for proposing this ticket",
                },
            },
            "required": ["title"],
        },
        category="tickets",
    ),
    ToolDefinition(
        name="ticket_get",
        description="Get details of a specific ticket by ID.",
        parameters={
            "type": "object",
            "properties": {
                "ticket_id": {
                    "type": "string",
                    "description": "The ticket UUID",
                },
            },
            "required": ["ticket_id"],
        },
        category="tickets",
    ),
    ToolDefinition(
        name="ticket_update",
        description="Update an existing ticket's title, description, priority, or labels.",
        parameters={
            "type": "object",
            "properties": {
                "ticket_id": {
                    "type": "string",
                    "description": "The ticket UUID",
                },
                "title": {
                    "type": "string",
                    "description": "New title",
                },
                "description": {
                    "type": "string",
                    "description": "New description",
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "critical"],
                    "description": "New priority level",
                },
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "New labels",
                },
            },
            "required": ["ticket_id"],
        },
        category="tickets",
    ),
    ToolDefinition(
        name="ticket_search",
        description="Search tickets by keyword in title and description.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query",
                },
            },
            "required": ["query"],
        },
        category="tickets",
    ),
    ToolDefinition(
        name="ticket_delete",
        description="Delete a ticket by ID. Use with caution.",
        parameters={
            "type": "object",
            "properties": {
                "ticket_id": {
                    "type": "string",
                    "description": "The ticket UUID to delete",
                },
            },
            "required": ["ticket_id"],
        },
        category="tickets",
    ),
    # Performance and monitoring
    ToolDefinition(
        name="monitoring_stats",
        description="Get Atlas monitoring statistics including token usage, rate limits, and system health.",
        parameters={
            "type": "object",
            "properties": {
                "hours": {
                    "type": "integer",
                    "description": "Hours of history to include",
                    "default": 24,
                },
            },
        },
        category="admin",
    ),
    ToolDefinition(
        name="performance_metrics",
        description="Get comprehensive Atlas performance metrics and health status.",
        parameters={
            "type": "object",
            "properties": {
                "hours": {
                    "type": "integer",
                    "description": "Hours of history to include",
                    "default": 24,
                },
            },
        },
        category="admin",
    ),
    # Jira advanced tools
    ToolDefinition(
        name="jira_get_remote_links",
        description="Get remote links (Confluence pages, external URLs) attached to a Jira issue.",
        parameters={
            "type": "object",
            "properties": {
                "issue_key": {
                    "type": "string",
                    "description": "The Jira issue key (e.g., 'ESD-123', 'SYS-456')",
                },
            },
            "required": ["issue_key"],
        },
        category="issues",
    ),
    ToolDefinition(
        name="jira_create_confluence_link",
        description="Create a remote link from a Jira issue to a Confluence page. Use this to link documentation to tickets.",
        parameters={
            "type": "object",
            "properties": {
                "issue_key": {
                    "type": "string",
                    "description": "The Jira issue key (e.g., 'ESD-123')",
                },
                "confluence_page_id": {
                    "type": "string",
                    "description": "The Confluence page ID to link to",
                },
                "title": {
                    "type": "string",
                    "description": "Optional link title (defaults to 'Confluence Page {page_id}')",
                },
                "relationship": {
                    "type": "string",
                    "description": "Relationship type (default 'Wiki Page')",
                    "default": "Wiki Page",
                },
            },
            "required": ["issue_key", "confluence_page_id"],
        },
        category="issues",
    ),
    ToolDefinition(
        name="jira_delete_remote_link",
        description="Delete a remote link from a Jira issue.",
        parameters={
            "type": "object",
            "properties": {
                "issue_key": {
                    "type": "string",
                    "description": "The Jira issue key",
                },
                "link_id": {
                    "type": "string",
                    "description": "The remote link ID to delete",
                },
            },
            "required": ["issue_key", "link_id"],
        },
        category="issues",
    ),
    ToolDefinition(
        name="jira_list_attachments",
        description="List all file attachments on a Jira issue.",
        parameters={
            "type": "object",
            "properties": {
                "issue_key": {
                    "type": "string",
                    "description": "The Jira issue key (e.g., 'ESD-123')",
                },
            },
            "required": ["issue_key"],
        },
        category="issues",
    ),
    ToolDefinition(
        name="jira_attach_file",
        description="Download a file from URL and attach it to a Jira issue. Useful for preserving attachments from external links.",
        parameters={
            "type": "object",
            "properties": {
                "issue_key": {
                    "type": "string",
                    "description": "The Jira issue key (e.g., 'ESD-123')",
                },
                "file_url": {
                    "type": "string",
                    "description": "URL to download the file from",
                },
                "filename": {
                    "type": "string",
                    "description": "Optional filename override",
                },
            },
            "required": ["issue_key", "file_url"],
        },
        category="issues",
    ),
    # Commvault backup tools
    ToolDefinition(
        name="commvault_backup_status",
        description="Get Commvault backup status and recent job history for a hostname or VM. Use this to check backup health and last successful backup times.",
        parameters={
            "type": "object",
            "properties": {
                "hostname": {
                    "type": "string",
                    "description": "Target hostname, client name, or VM name to search",
                },
                "hours": {
                    "type": "integer",
                    "description": "Hours of history to look back (default 24)",
                    "default": 24,
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of jobs to return (default 10)",
                    "default": 10,
                },
            },
            "required": ["hostname"],
        },
        category="backup",
    ),
    # Confluence RAG advanced tools
    ToolDefinition(
        name="get_confluence_page",
        description="Get full content of a specific Confluence page by page ID or title. Use when you need the complete documentation.",
        parameters={
            "type": "object",
            "properties": {
                "page_id": {
                    "type": "string",
                    "description": "The Confluence page ID (if known)",
                },
                "page_title": {
                    "type": "string",
                    "description": "The page title to search for (use with space_key)",
                },
                "space_key": {
                    "type": "string",
                    "description": "The Confluence space key (e.g., 'SYS', 'NET')",
                },
            },
        },
        category="documentation",
    ),
    ToolDefinition(
        name="list_confluence_spaces",
        description="List all available Confluence spaces in the documentation index.",
        parameters={
            "type": "object",
            "properties": {},
        },
        category="documentation",
    ),
    ToolDefinition(
        name="generate_guide_from_docs",
        description="""Generate a comprehensive guide by searching documentation and returning FULL page content from multiple relevant pages.

Use this when you need to:
- Create a complete how-to guide from internal documentation
- Compile information from multiple related pages
- Get detailed procedures with all steps and context

Returns full page content (not just snippets) from the most relevant documentation.""",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to search for (e.g., 'configure MS Defender', 'CEPH tenant setup')",
                },
                "max_pages": {
                    "type": "integer",
                    "description": "Maximum number of relevant pages to include (default 5)",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
        category="documentation",
    ),
]


def get_tool_definitions(categories: list[str] | None = None) -> list[ToolDefinition]:
    """Get tool definitions, optionally filtered by category."""
    if categories is None:
        return ATLAS_TOOLS
    return [tool for tool in ATLAS_TOOLS if tool.category in categories]


def create_atlas_tools() -> list[dict[str, Any]]:
    """Create tool definitions in OpenAI format."""
    return [tool.to_openai_format() for tool in ATLAS_TOOLS]


def get_tools_by_category() -> dict[str, list[ToolDefinition]]:
    """Get tools organized by category."""
    categorized: dict[str, list[ToolDefinition]] = {}
    for tool in ATLAS_TOOLS:
        if tool.category not in categorized:
            categorized[tool.category] = []
        categorized[tool.category].append(tool)
    return categorized

