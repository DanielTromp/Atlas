# Atlas MCP Server

The Atlas MCP Server provides Claude with direct access to infrastructure systems without requiring the Atlas API server to be running.

## Quick Start

### Claude Desktop Configuration

Add to `~/.config/claude/claude_desktop_config.json`:

```json
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
```

Restart Claude Desktop after configuration changes.

## Available Tools

### NetBox

#### `atlas_netbox_search`
Search NetBox for devices, VMs, or IP addresses.

**Parameters:**
- `query` (string, required): Search query (hostname, IP, or partial name)
- `limit` (integer, default: 50): Maximum results to return

**Example:** Search for all devices containing "web" in their name or IP.

---

### vCenter

#### `atlas_vcenter_list_instances`
List all configured vCenter instances with their status and cached VM counts.

**Parameters:** None

**Returns:** List of vCenter configurations with connection status.

#### `atlas_vcenter_get_vms`
Get VMs from a specific vCenter instance.

**Parameters:**
- `config_id` (string, required): The vCenter configuration ID
- `limit` (integer, default: 20, max: 50): Maximum VMs to return
- `search` (string, optional): Filter VMs by name

**Example:** Get all VMs containing "prod" from a specific vCenter.

---

### Zabbix

#### `atlas_zabbix_alerts`
Get current Zabbix alerts (active problems).

**Parameters:**
- `min_severity` (integer, default: 0): Minimum severity level (0-5)
  - 0: Not classified
  - 1: Information
  - 2: Warning
  - 3: Average
  - 4: High
  - 5: Disaster
- `unacknowledged_only` (boolean, default: false): Only show unacknowledged problems
- `limit` (integer, default: 50): Maximum alerts to return
- `search` (string, optional): Filter by problem name or host

**Example:** Get all high-severity unacknowledged alerts.

---

### Jira

#### `atlas_jira_search`
Search Jira issues using JQL or free-text.

**Parameters:**
- `jql` (string, optional): Explicit JQL query (overrides other filters)
- `query` (string, optional): Free-text search across summary, description, comments
- `project` (string, optional): Filter by project key
- `max_results` (integer, default: 20): Maximum issues to return

**Example:** Search for all open issues mentioning "database" in project ESD.

#### `atlas_jira_get_remote_links`
Get remote links for a Jira issue.

**Parameters:**
- `issue_key` (string, required): The Jira issue key (e.g., "ESD-123")

#### `atlas_jira_create_confluence_link`
Create a remote link from a Jira issue to a Confluence page.

**Parameters:**
- `issue_key` (string, required): The Jira issue key (e.g., "ESD-123")
- `confluence_page_id` (string, required): The Confluence page ID
- `title` (string, optional): Link title (defaults to "Confluence Page {page_id}")
- `relationship` (string, default: "Wiki Page"): Relationship type

#### `atlas_jira_delete_remote_link`
Delete a remote link from a Jira issue.

**Parameters:**
- `issue_key` (string, required): The Jira issue key
- `link_id` (string, required): The remote link ID to delete

#### `atlas_jira_attach_file`
Download a file from a URL and attach it to a Jira issue.

**Parameters:**
- `issue_id_or_key` (string, required): The Jira issue key or ID
- `file_url` (string, required): URL to download the file from
- `filename` (string, optional): Override filename

**Example:** Attach a power report PDF from an external URL to a ticket.

#### `atlas_jira_attach_files`
Batch download and attach multiple files to a Jira issue.

**Parameters:**
- `issue_id_or_key` (string, required): The Jira issue key or ID
- `files` (array, required): List of objects with `url` and optional `filename`

#### `atlas_jira_list_attachments`
List all attachments on a Jira issue.

**Parameters:**
- `issue_id_or_key` (string, required): The Jira issue key or ID

---

### Confluence

#### `atlas_confluence_search`
Search Confluence pages using CQL (Confluence Query Language).

**Parameters:**
- `cql` (string, optional): Explicit CQL query (overrides other filters)
- `query` (string, optional): Free-text search
- `space` (string, optional): Filter by space key
- `max_results` (integer, default: 20): Maximum results to return

**Example:** Search for pages mentioning "deployment" in the OPS space.

---

### Commvault

#### `atlas_commvault_info`
Get Commvault backup status and job history for a hostname.

**Parameters:**
- `hostname` (string, required): Target hostname or client name to search
- `hours` (integer, default: 24): Hours of history to look back
- `limit` (integer, default: 10): Maximum jobs to return

**Example:** Check backup status for server "db-prod-01" over the last 48 hours.

---

### Unified Search

#### `atlas_search`
Search across all Atlas systems at once (NetBox, vCenter, Zabbix, Jira, Confluence, Commvault).

**Parameters:**
- `query` (string, required): Search query (hostname, IP, ticket ID, etc.)
- `limit` (integer, default: 10): Maximum results per system

**Example:** Search for "web-server-01" across all systems to see:
- NetBox device/VM entries
- vCenter VM status
- Active Zabbix alerts
- Related Jira tickets
- Confluence documentation
- Backup job history

---

## Environment Variables

All integrations are optional. Missing credentials will show helpful error messages.

| Variable | Description | Required For |
|----------|-------------|--------------|
| `NETBOX_URL` | NetBox instance URL | NetBox tools |
| `NETBOX_TOKEN` | NetBox API token | NetBox tools |
| `ATLASSIAN_BASE_URL` | Atlassian Cloud URL | Jira, Confluence |
| `ATLASSIAN_EMAIL` | Atlassian account email | Jira, Confluence |
| `ATLASSIAN_API_TOKEN` | Atlassian API token | Jira, Confluence |
| `ZABBIX_API_URL` | Zabbix API endpoint | Zabbix tools |
| `ZABBIX_API_TOKEN` | Zabbix API token | Zabbix tools |
| `COMMVAULT_BASE_URL` | Commvault API URL | Commvault tools |
| `COMMVAULT_API_TOKEN` | Commvault API token | Commvault tools |

## Architecture

The MCP server accesses infrastructure systems directly using Python clients:

```
Claude Desktop
     │
     ▼
┌─────────────────────────────────────┐
│     Atlas MCP Server (Python)       │
│     scripts/run_mcp.py              │
└──────────────┬──────────────────────┘
               │
    ┌──────────┼──────────┬──────────┬──────────┐
    ▼          ▼          ▼          ▼          ▼
 NetBox    vCenter    Zabbix    Atlassian   Commvault
 Client    Service    Client     Client      Client
```

This direct approach:
- Does not require the Atlas API server to be running
- Reduces latency (no HTTP round-trips)
- Simplifies deployment (single process)

## Troubleshooting

### Server not starting
Check Claude Desktop logs for error messages. Common issues:
- Missing Python dependencies: Run `uv sync` in the Atlas directory
- Invalid credentials: Verify environment variables in config

### Tool returns "Not Configured"
The required environment variables for that system are missing. Check the env section in your Claude Desktop config.

### Slow startup
The server takes ~3-5 seconds to start. This is normal due to Python imports and database initialization.
