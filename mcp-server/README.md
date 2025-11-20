# Atlas MCP Server

Model Context Protocol (MCP) server for Infrastructure Atlas. This server enables Claude and other MCP clients to interact with your Atlas infrastructure management API.

## Features

The Atlas MCP server provides tools and resources for:

- **vCenter Management**: List instances, get VM inventories, refresh data
- **NetBox Inventory**: Search devices, VMs, and infrastructure records
- **Zabbix Monitoring**: Query current alerts and problems
- **Jira Integration**: Search issues across projects
- **Confluence Knowledge**: Search documentation and pages
- **Performance Monitoring**: View Atlas metrics, token usage, and health status
- **Tools Catalog**: Access the full catalog of available Atlas agents

## Installation

### Option 1: Install from source (development)

```bash
cd mcp-server
uv pip install -e .
```

### Option 2: Install with pip

```bash
pip install -e mcp-server/
```

## Quick Setup

### Automated Setup (Recommended)

Run the setup script to automatically configure Claude Desktop:

```bash
cd mcp-server
export ATLAS_API_URL=http://127.0.0.1:8000
export ATLAS_API_TOKEN=your_token_here
python setup_claude.py
```

The script will:
- Detect your Claude Desktop configuration location
- Add the Atlas MCP server configuration
- Set up environment variables

After running the script, restart Claude Desktop.

## Manual Configuration

### 1. Set up environment variables

Create a `.env` file in the `mcp-server` directory:

```bash
# Atlas API connection
ATLAS_API_URL=http://127.0.0.1:8000
ATLAS_API_TOKEN=your_api_token_here

# Optional: SSL verification (default: true)
ATLAS_VERIFY_SSL=true
```

Or set environment variables directly:

```bash
export ATLAS_API_URL=https://atlas.example.com
export ATLAS_API_TOKEN=your_token
```

### 2. Configure Claude Desktop

Add the MCP server to your Claude Desktop configuration file:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "atlas": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/path/to/Atlas/mcp-server",
        "atlas-mcp"
      ],
      "env": {
        "ATLAS_API_URL": "http://127.0.0.1:8000",
        "ATLAS_API_TOKEN": "your_api_token_here"
      }
    }
  }
}
```

Or if installed globally:

```json
{
  "mcpServers": {
    "atlas": {
      "command": "atlas-mcp",
      "env": {
        "ATLAS_API_URL": "http://127.0.0.1:8000",
        "ATLAS_API_TOKEN": "your_api_token_here"
      }
    }
  }
}
```

### 3. Restart Claude Desktop

After updating the configuration, restart Claude Desktop to load the MCP server.

## Available Tools

### vCenter Operations

- **atlas_vcenter_list_instances**: List all configured vCenter instances with status
- **atlas_vcenter_get_vms**: Get VMs from a specific vCenter (with optional refresh)
- **atlas_vcenter_refresh**: Force refresh vCenter inventory from live API

### Infrastructure Inventory

- **atlas_netbox_search**: Search NetBox for devices, VMs, or all records

### Monitoring & Alerting

- **atlas_zabbix_alerts**: Get current Zabbix alerts with severity/group filters

### Atlassian Integration

- **atlas_jira_search**: Search Jira issues with filters
- **atlas_confluence_search**: Search Confluence pages and documentation

### Cross-System Search

- **atlas_search_aggregate**: Search across all systems simultaneously (Zabbix, Jira, Confluence, vCenter, NetBox)

### Performance & Metrics

- **atlas_monitoring_stats**: Get token usage and rate limiting statistics
- **atlas_performance_metrics**: Get comprehensive health and performance data
- **atlas_tools_catalog**: View all available Atlas tools and agents

## Available Resources

Resources provide read-only access to Atlas data:

- `atlas://vcenter/instances` - List of vCenter instances
- `atlas://monitoring/performance` - Current performance metrics
- `atlas://tools/catalog` - Full tools catalog

## Usage Examples

Once configured in Claude Desktop, you can ask Claude to:

### Infrastructure Queries

> "Show me all vCenter instances in Atlas"

> "Get the VMs from vCenter config abc-123"

> "Search NetBox for devices matching 'edge01'"

### Monitoring

> "What are the current high-severity Zabbix alerts?"

> "Show me unacknowledged alerts in Zabbix group 42"

### Documentation & Issues

> "Search Confluence for SIP trunk documentation"

> "Find open Jira issues in the SYS project"

### Cross-System Search

> "Search all systems for 'vw746'"

> "Find any mentions of 'core-router' across Atlas"

### Performance

> "What's the performance status of Atlas right now?"

> "Show token usage for the last 24 hours"

## Development

### Running Tests

```bash
cd mcp-server
uv run pytest
```

### Code Quality

```bash
# Format code
uv run ruff format .

# Lint code
uv run ruff check .
```

### Running the Server Standalone

For testing, you can run the MCP server directly:

```bash
cd mcp-server
export ATLAS_API_URL=http://127.0.0.1:8000
export ATLAS_API_TOKEN=your_token
uv run atlas-mcp
```

The server communicates via stdio and expects MCP protocol messages on stdin.

## Troubleshooting

### Connection Issues

1. Ensure Atlas API is running:
   ```bash
   uv run atlas api serve --host 127.0.0.1 --port 8000
   ```

2. Verify API token is correct and set in environment

3. Check SSL verification settings if using HTTPS

### Claude Desktop Not Finding Tools

1. Check Claude Desktop logs:
   - macOS: `~/Library/Logs/Claude/mcp-server-atlas.log`
   - Windows: `%APPDATA%\Claude\Logs\mcp-server-atlas.log`

2. Verify the path in `claude_desktop_config.json` is absolute

3. Ensure environment variables are set in the config

### API Errors

- Check Atlas API is accessible: `curl http://127.0.0.1:8000/health`
- Verify authentication token is valid
- Check Atlas API logs for errors

## Architecture

```
┌─────────────────┐
│  Claude Desktop │
└────────┬────────┘
         │ MCP Protocol (stdio)
         │
┌────────▼────────┐
│  Atlas MCP      │
│    Server       │
└────────┬────────┘
         │ HTTP/HTTPS
         │
┌────────▼────────┐
│  Atlas API      │
│  (FastAPI)      │
└────────┬────────┘
         │
    ┌────▼────┐
    │ vCenter │
    │ NetBox  │
    │ Zabbix  │
    │ Jira    │
    │etc.     │
    └─────────┘
```

## Security Notes

- **API Token**: Store your `ATLAS_API_TOKEN` securely. Do not commit it to version control.
- **SSL Verification**: Keep `ATLAS_VERIFY_SSL=true` in production environments.
- **Network Access**: Ensure the MCP server can reach your Atlas API (firewall rules, VPN, etc.)

## License

MIT

## Contributing

Contributions welcome! Please follow the Atlas project's coding standards:

- Python 3.11+
- 4-space indentation
- Maximum line length: 120 characters
- Use ruff for formatting and linting
- All code and comments in English

## Support

For issues or questions:

1. Check Atlas API documentation: `docs/` directory
2. Review Atlas CLAUDE.md for project guidelines
3. File issues on the Atlas GitHub repository
