#!/usr/bin/env python3
"""
Unified Atlas MCP Server for Claude integration.

Provides Claude with direct access to infrastructure systems:
- NetBox (devices, VMs, IPs)
- vCenter (VM inventory)
- Zabbix (monitoring alerts)
- Jira (issues, attachments, remote links)
- Confluence (CQL search)
- Commvault (backup status)
- Unified cross-system search

Claude Desktop configuration (~/.config/claude/claude_desktop_config.json):

{
    "mcpServers": {
        "atlas": {
            "command": "uv",
            "args": ["run", "--directory", "/path/to/Atlas", "python", "scripts/run_mcp.py"],
            "env": {
                "NETBOX_URL": "https://netbox.example.com",
                "NETBOX_TOKEN": "your-token",
                "ATLASSIAN_BASE_URL": "https://your-org.atlassian.net",
                "ATLASSIAN_EMAIL": "your-email@example.com",
                "ATLASSIAN_API_TOKEN": "your-api-token",
                "ZABBIX_API_URL": "https://zabbix.example.com/api_jsonrpc.php",
                "ZABBIX_API_TOKEN": "your-zabbix-token",
                "COMMVAULT_BASE_URL": "https://commvault.example.com/webconsole/api",
                "COMMVAULT_API_TOKEN": "your-commvault-token"
            }
        }
    }
}

All integrations are optional - missing credentials show helpful errors.
"""

import asyncio
import logging
import os
import sys

# =============================================================================
# CRITICAL: Suppress logging before imports - MCP uses stdout for JSON-RPC
# =============================================================================

for logger_name in ["alembic", "alembic.runtime", "alembic.runtime.migration"]:
    logging.getLogger(logger_name).disabled = True

logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("httpcore").setLevel(logging.ERROR)

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def log(msg: str) -> None:
    """Log to stderr (MCP uses stdout for protocol)."""
    print(msg, file=sys.stderr, flush=True)


if __name__ == "__main__":
    log("Atlas MCP: Starting...")

    from infrastructure_atlas.confluence_rag.mcp_server import AtlasMCPServer

    # Create server without RAG for fast startup (~3 seconds)
    # RAG tools require embedding model which takes 15+ seconds to load
    server = AtlasMCPServer(search_engine=None, db=None, settings=None)

    tool_count = len(server.server._tool_manager._tools)
    log(f"Atlas MCP: Ready with {tool_count} tools")

    asyncio.run(server.run())
