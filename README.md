<p align="center">
  <img src="src/infrastructure_atlas/api/static/logo.png" alt="Infrastructure Atlas" width="120" />
</p>

<h1 align="center">Infrastructure Atlas</h1>

<p align="center">
  <strong>Unified infrastructure management dashboard</strong><br>
  Aggregate, search, and manage infrastructure data from NetBox, Commvault, Zabbix, Confluence, Jira, vCenter, Foreman, and Puppet — all in one place.
</p>

<p align="center">
  <a href="#features">Features</a> •
  <a href="#screenshots">Screenshots</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="#documentation">Documentation</a> •
  <a href="#license">License</a>
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
| **Confluence** | CQL search, CMDB publishing, table sync |
| **Jira** | Issue search with filters, project/status/assignee views |
| **vCenter** | VM inventory, placement coverage, cluster visibility |
| **Foreman** | Host inventory, Puppet configuration visibility |
| **Puppet** | User/group management, access matrix, security analysis |

### Highlights

- 🔍 **Cross-system search** — Query all integrations from a single interface
- 📊 **Virtual scrolling** — Handle thousands of records smoothly
- 🔐 **Secure by default** — Bearer token API auth, session-based UI login
- 📤 **Automated exports** — CSV, Excel, and Confluence publishing
- ⚡ **Fast caching** — TTL-based caches with hit/miss instrumentation
- 🖥️ **Modern UI** — Responsive design with dark mode support

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) package manager

### Installation

```bash
# Clone the repository
git clone https://github.com/your-org/infrastructure-atlas.git
cd infrastructure-atlas

# Copy environment template
cp .env.example .env

# Edit .env with your credentials
# At minimum: NETBOX_URL, NETBOX_TOKEN
```

### Basic Usage

```bash
# Check connectivity
uv run atlas status

# Start the web UI
uv run atlas api serve --host 127.0.0.1 --port 8000

# Open http://127.0.0.1:8000/app/ in your browser
```

### Common Commands

```bash
# Export NetBox data
uv run atlas export update --force

# Search across systems
uv run atlas search run --q "server-name" --json

# View Zabbix problems
uv run atlas zabbix dashboard --unack-only
```

## Documentation

| Document | Description |
|----------|-------------|
| [Getting Started](docs/getting-started.md) | Installation, setup, and first steps |
| [Configuration](docs/configuration.md) | Environment variables and settings |
| [CLI Reference](docs/cli-reference.md) | Complete command-line interface guide |
| [API Reference](docs/api-reference.md) | REST API endpoints and usage |
| [Web UI Guide](docs/web-ui.md) | Frontend features and navigation |

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
│   └── env.py                  # Environment loader
├── netbox-export/bin/          # Export scripts
├── data/                       # Output directory (CSV/Excel)
├── docs/                       # Documentation
└── scripts/                    # Utility scripts
```

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

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

---

<p align="center">
  <sub>Built with ❤️ for infrastructure teams</sub>
</p>
