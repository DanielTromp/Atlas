# Atlas MCP Server - Setup Guide

This guide will help you get the Atlas MCP server running with Claude Desktop.

## What is this?

The Atlas MCP (Model Context Protocol) server enables Claude to interact directly with your Atlas infrastructure management API. Once configured, you can ask Claude natural language questions about your infrastructure and it will use the Atlas API to get real-time data.

## What You Can Do

With this MCP server, Claude can:

- **Query vCenter**: List instances, get VM inventories, refresh data
- **Search NetBox**: Find devices, VMs, and infrastructure records
- **Check Zabbix**: View current alerts and monitoring problems
- **Search Jira**: Find issues across projects
- **Search Confluence**: Look up documentation and runbooks
- **Cross-System Search**: Search across all systems simultaneously
- **Monitor Performance**: View Atlas health metrics and token usage

## Prerequisites

1. **Atlas API Running**: Your Atlas API must be accessible
   ```bash
   # Start Atlas API if not already running
   cd /Users/daniel/Documents/code/Atlas
   uv run atlas api serve --host 127.0.0.1 --port 8000
   ```

2. **API Token**: You need an Atlas API token
   - Set in Atlas `.env` file: `ATLAS_API_TOKEN=your_token_here`
   - Or configure via the Atlas web UI

3. **Claude Desktop**: Download from https://claude.ai/download

## Installation Steps

### Option 1: Automated Setup (Easiest)

```bash
cd /Users/daniel/Documents/code/Atlas/mcp-server

# Set your API credentials
export ATLAS_API_URL=http://127.0.0.1:8000
export ATLAS_API_TOKEN=your_token_here

# Run setup script
python setup_claude.py
```

The script will automatically configure Claude Desktop. Just restart Claude Desktop when done!

### Option 2: Manual Setup

1. **Create Configuration File**

   Edit (or create) `~/Library/Application Support/Claude/claude_desktop_config.json`:

   ```json
   {
     "mcpServers": {
       "atlas": {
         "command": "uv",
         "args": [
           "run",
           "--directory",
           "/Users/daniel/Documents/code/Atlas/mcp-server",
           "atlas-mcp"
         ],
         "env": {
           "ATLAS_API_URL": "http://127.0.0.1:8000",
           "ATLAS_API_TOKEN": "your_token_here"
         }
       }
     }
   }
   ```

2. **Restart Claude Desktop**

## Verification

1. **Start Atlas API** (if not running):
   ```bash
   uv run atlas api serve
   ```

2. **Open Claude Desktop**
   - Look for the 🔌 icon in the bottom-right
   - It should show "atlas" as connected

3. **Test it!**
   Ask Claude:
   > "Show me all vCenter instances in Atlas"

   Or:
   > "What are the current Zabbix alerts?"

## Example Queries

### Infrastructure

- "List all vCenter instances and their VM counts"
- "Get VMs from vCenter config abc-123"
- "Search NetBox for devices named 'edge01'"
- "Find any infrastructure containing 'router' across all systems"

### Monitoring

- "Show me high-severity Zabbix alerts"
- "What are the unacknowledged Zabbix problems?"
- "What's Atlas performance status right now?"

### Documentation & Issues

- "Search Confluence for SIP trunk documentation"
- "Find open Jira issues in the SYS project"
- "Search all systems for 'vw746'"

## Troubleshooting

### Claude Can't Connect to MCP Server

1. **Check Atlas API is running**:
   ```bash
   curl http://127.0.0.1:8000/health
   ```

2. **Check Claude Desktop logs**:
   ```bash
   tail -f ~/Library/Logs/Claude/mcp-server-atlas.log
   ```

3. **Verify configuration path**:
   ```bash
   cat ~/Library/Application\ Support/Claude/claude_desktop_config.json
   ```

### API Errors

1. **Test API token**:
   ```bash
   curl -H "Authorization: Bearer your_token" http://127.0.0.1:8000/api/vcenter/instances
   ```

2. **Check Atlas logs**:
   ```bash
   tail -f logs/atlas.log
   ```

### MCP Server Not Starting

1. **Test manually**:
   ```bash
   cd /Users/daniel/Documents/code/Atlas/mcp-server
   export ATLAS_API_URL=http://127.0.0.1:8000
   export ATLAS_API_TOKEN=your_token
   uv run atlas-mcp
   # Press Ctrl+C to exit
   ```

2. **Check dependencies**:
   ```bash
   cd /Users/daniel/Documents/code/Atlas/mcp-server
   uv pip install -e .
   ```

## HTTPS Setup

If your Atlas API uses HTTPS with a self-signed certificate:

```json
{
  "mcpServers": {
    "atlas": {
      "command": "uv",
      "args": ["run", "--directory", "/Users/daniel/Documents/code/Atlas/mcp-server", "atlas-mcp"],
      "env": {
        "ATLAS_API_URL": "https://atlas.example.com",
        "ATLAS_API_TOKEN": "your_token_here",
        "ATLAS_VERIFY_SSL": "false"
      }
    }
  }
}
```

**Warning**: Only use `ATLAS_VERIFY_SSL=false` for development/testing!

## Development

### Running Tests

```bash
cd /Users/daniel/Documents/code/Atlas/mcp-server
uv run pytest
```

### Code Quality

```bash
# Format code
uv run ruff format .

# Lint code
uv run ruff check .
```

## File Structure

```
mcp-server/
├── src/atlas_mcp/
│   ├── __init__.py          # Package initialization
│   └── server.py            # Main MCP server implementation
├── tests/
│   ├── __init__.py
│   └── test_server.py       # Tests
├── pyproject.toml           # Dependencies and build config
├── README.md                # Full documentation
├── SETUP_GUIDE.md          # This file
├── setup_claude.py          # Automated setup script
├── .env.example             # Environment variables template
└── .gitignore              # Git ignore rules
```

## Next Steps

1. ✅ Configure and test the MCP server
2. Try asking Claude infrastructure questions
3. Explore the full API capabilities in README.md
4. Configure additional Atlas integrations (Commvault, etc.)

## Support

For issues or questions:
- Review Atlas documentation in `/Users/daniel/Documents/code/Atlas/docs/`
- Check `CLAUDE.md` for project guidelines
- File issues on the Atlas GitHub repository

## Security Notes

- **Never commit** your `ATLAS_API_TOKEN` to version control
- Keep `ATLAS_VERIFY_SSL=true` in production
- Secure your Atlas API with proper authentication
- Review MCP server logs periodically

---

Enjoy using Atlas with Claude! 🚀
