<p align="center">
  <img src="src/infrastructure_atlas/api/static/logo.png" alt="Infrastructure Atlas" width="120" />
</p>

<h1 align="center">Infrastructure Atlas</h1>

<p align="center">
  <strong>Unified infrastructure management with AI-powered agents</strong><br>
  Aggregate, search, and manage infrastructure data from NetBox, Commvault, Zabbix, Confluence, Jira, vCenter, Foreman, and Puppet — with AI agents accessible via Web, Slack, and Telegram.
</p>

<p align="center">
  <a href="#features">Features</a> •
  <a href="#ai-agents">AI Agents</a> •
  <a href="#bot-integrations">Bot Integrations</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="#documentation">Documentation</a>
</p>

---

## Screenshots

<table>
  <tr>
    <td align="center">
      <img src="docs/assets/login.png" alt="Login Screen" width="400" /><br>
      <em>Secure login with session management</em>
    </td>
    <td align="center">
      <img src="docs/assets/dashboard.png" alt="Dashboard" width="400" /><br>
      <em>Unified infrastructure dashboard</em>
    </td>
  </tr>
</table>

## Features

| Integration | Capabilities |
|-------------|-------------|
| **NetBox** | Device & VM inventory, live search, CMDB export |
| **Commvault** | Backup job monitoring, storage pools, retention analysis |
| **Zabbix** | Problems dashboard, host groups, bulk acknowledgment |
| **Confluence** | Semantic search (RAG), CMDB publishing, runbook lookup |
| **Jira** | Issue search with JQL, ticket triage, assignment suggestions |
| **vCenter** | VM inventory, placement coverage, cluster visibility |
| **Foreman** | Host inventory, Puppet configuration visibility |
| **Puppet** | User/group management, access matrix, security analysis |

### Highlights

- 🤖 **AI Agents** — Specialized agents for triage, engineering, and review tasks
- 💬 **Multi-Platform Bots** — Chat with agents via Slack, Telegram, or Web UI
- 🔍 **Cross-system search** — Query all integrations from a single interface
- 📊 **Excel Exports** — Export search results and reports directly to Slack/Telegram
- 🔐 **Secure by default** — Bearer token API auth, session-based UI login
- 📚 **Confluence RAG** — Semantic search across documentation with citations
- ⚡ **Fast caching** — TTL-based caches with hit/miss instrumentation

## AI Agents

Infrastructure Atlas includes AI-powered agents that can interact with your infrastructure systems.

### Available Agents

| Agent | Purpose | Skills |
|-------|---------|--------|
| **Triage** (`@triage`) | Ticket analysis, categorization, quick lookups | Jira, Confluence |
| **Engineer** (`@engineer`) | Technical investigation, infrastructure queries | Jira, NetBox, Zabbix, vCenter, Commvault |
| **Reviewer** (`@reviewer`) | Quality review, validation | Jira, Confluence |

### Example Interactions

```
# Via Slack/Telegram
@triage Show me open tickets for the Systems team
@engineer Check backup status for server web-prod-01
@triage Export resolved tickets from last week as Excel
```

### Capabilities

- **Jira Integration**: Search issues, analyze tickets, suggest assignments
- **NetBox Queries**: Look up devices, VMs, IP addresses
- **Zabbix Monitoring**: Check active alerts and problems
- **Confluence RAG**: Semantic search across runbooks and documentation
- **Data Exports**: Generate Excel reports from queries

## Bot Integrations

Chat with Atlas agents through your preferred platform.

### Slack Bot

Full-featured Slack integration using Socket Mode (no public endpoints required).

```bash
# Configure
SLACK_BOT_TOKEN=xoxb-your-token
SLACK_APP_TOKEN=xapp-your-app-token

# Run
uv run atlas bots run slack
```

**Features:**
- Direct messages and channel mentions
- Rich Block Kit formatting with dividers
- Thread-based conversation memory
- File exports (Excel, CSV) uploaded directly to Slack
- Commands: `!help`, `!status`, `!agents`, `!link <code>`

### Telegram Bot

Polling-based Telegram bot for internal deployments.

```bash
# Configure
TELEGRAM_BOT_TOKEN=your-bot-token

# Run
uv run atlas bots run telegram
```

**Features:**
- HTML formatting for clean messages
- Compact responses within Telegram limits
- File exports sent as documents
- Commands: `/help`, `/status`, `/agents`, `/link <code>`

### Account Linking

Users must link their platform accounts to Atlas for authorization:

```bash
# Generate verification code
uv run atlas bots link-user <username> slack

# User sends to bot
!link <code>   # Slack
/link <code>   # Telegram
```

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) package manager
- MongoDB (optional, for high-concurrency deployments)
- Docker (optional, for Qdrant vector search)

### Installation

```bash
# Clone the repository
git clone https://github.com/your-org/infrastructure-atlas.git
cd infrastructure-atlas

# Copy environment template
cp .env.example .env

# Edit .env with your credentials
# Required: NETBOX_URL, NETBOX_TOKEN, ANTHROPIC_API_KEY
```

### Basic Usage

```bash
# Start the web UI and API (development)
uv run atlas api serve --host 127.0.0.1 --port 8000

# Open http://127.0.0.1:8000/app/ in your browser
```

### Production Deployment

```bash
# Production server (optimized startup, multiple workers)
uv run atlas api prod --host 0.0.0.0 --port 8000 --workers 4

# Fast development (skip heavy AI imports)
ATLAS_LAZY_AI_IMPORTS=1 uv run atlas api serve
```

### Container Deployment (Docker/Podman)

```bash
# Start full stack (Atlas + MongoDB)
docker compose up -d

# With RAG support (adds Qdrant)
docker compose --profile rag up -d

# With chat bots
docker compose --profile bots up -d

# View logs
docker compose logs -f atlas

# Stop
docker compose down
```

See [Container Deployment Guide](docs/deployment.md) for detailed instructions.

### Running Bots

```bash
# Slack bot (Socket Mode)
uv run atlas bots run slack

# Telegram bot (Polling)
uv run atlas bots run telegram
```

### Common Commands

```bash
# Export NetBox data to Excel
uv run atlas export update --force

# Search across all systems
uv run atlas search run --q "server-name" --json

# View Zabbix problems
uv run atlas zabbix dashboard --unack-only

# Check bot status
uv run atlas bots status
```

## Documentation

| Document | Description |
|----------|-------------|
| [Getting Started](docs/getting-started.md) | Installation, setup, and first steps |
| [Container Deployment](docs/deployment.md) | Docker/Podman deployment guide |
| [Configuration](docs/configuration.md) | Environment variables and settings |
| [AI Chat](docs/ai-chat.md) | AI agent configuration and usage |
| [Agent Playground](docs/playground.md) | Interactive agent testing environment |
| [Bot System](docs/bots.md) | Slack, Telegram, and Teams bot setup |
| [Confluence RAG](docs/confluence_rag_setup.md) | Semantic search setup with Qdrant |

### Integration Guides

| Integration | Guide |
|-------------|-------|
| NetBox | [docs/integrations/netbox.md](docs/integrations/netbox.md) |
| Commvault | [docs/integrations/commvault.md](docs/integrations/commvault.md) |
| Zabbix | [docs/integrations/zabbix.md](docs/integrations/zabbix.md) |
| Confluence | [docs/integrations/confluence.md](docs/integrations/confluence.md) |
| Jira | [docs/integrations/jira.md](docs/integrations/jira.md) |
| vCenter | [docs/integrations/vcenter.md](docs/integrations/vcenter.md) |
| Foreman | [docs/integrations/foreman.md](docs/integrations/foreman.md) |
| Puppet | [docs/integrations/puppet.md](docs/integrations/puppet.md) |

## Project Structure

```
infrastructure-atlas/
├── src/infrastructure_atlas/   # Main package
│   ├── cli.py                  # Typer CLI entry point
│   ├── api/                    # FastAPI app + static UI
│   ├── agents/                 # AI agent definitions
│   ├── bots/                   # Platform bot adapters
│   │   ├── orchestrator.py     # Message routing & formatting
│   │   ├── adapters/           # Slack, Telegram, Teams
│   │   └── formatters.py       # Platform-specific formatting
│   ├── skills/                 # Agent skill implementations
│   │   ├── jira/               # Jira integration
│   │   ├── confluence/         # Confluence + RAG search
│   │   └── netbox/             # NetBox queries
│   └── confluence_rag/         # Vector search with Qdrant
├── mcp-server/                 # MCP server for Claude Desktop
├── data/                       # Cache and export directory
├── docs/                       # Documentation
└── scripts/                    # Utility scripts
```

## MCP Server

This repository includes a [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server that allows Claude Desktop to inspect your infrastructure.

### Installation

```bash
cd mcp-server
npm install
npm run install:mcp  # Updates claude_desktop_config.json
```

Restart Claude Desktop after installation. See [mcp-server/README.md](mcp-server/README.md) for details.

## Development

```bash
# Lint
uv run ruff check .

# Format
uv run ruff format .

# Type check
uv run mypy src

# Run tests
uv run pytest
```

### Storage Backends

Atlas supports two storage backends:

- **SQLite** (default): Simple file-based storage
- **MongoDB**: Recommended for high-concurrency bot deployments

```bash
# Enable MongoDB
ATLAS_STORAGE_BACKEND=mongodb
MONGODB_URI=mongodb://localhost:27017
```

## Environment Variables

Key configuration options:

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | API key for Claude AI models |
| `NETBOX_URL`, `NETBOX_TOKEN` | NetBox API connection |
| `ATLASSIAN_BASE_URL`, `ATLASSIAN_API_TOKEN` | Jira/Confluence API |
| `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN` | Slack bot credentials |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `ATLAS_STORAGE_BACKEND` | `sqlite` or `mongodb` |
| `QDRANT_URL` | Vector database for Confluence RAG |
| `ATLAS_SKIP_DB_HEALTH_CHECK` | Skip MongoDB health check at startup (faster boot) |
| `ATLAS_LAZY_AI_IMPORTS` | Defer loading heavy AI libraries (transformers, langchain) |

See [.env.example](.env.example) for the full list.

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

---

<p align="center">
  <sub>Built with ❤️ for infrastructure teams</sub>
</p>
