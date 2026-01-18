# Web UI Guide

The Infrastructure Atlas web interface provides a unified dashboard for managing infrastructure data.

## Accessing the UI

```bash
# Start the server
uv run atlas api serve --host 127.0.0.1 --port 8000

# Open in browser
http://127.0.0.1:8000/app/
```

If `ATLAS_UI_PASSWORD` is set, you'll see a login page first.

## Navigation

The top navigation bar provides access to all modules:

| Page | Description |
|------|-------------|
| **Zabbix** | Problems overview, host groups, bulk acknowledge |
| **NetBox** | Live search across devices and VMs |
| **Jira** | Issue search with filters |
| **Confluence** | CQL content search |
| **Foreman** | Host inventory, Puppet visibility |
| **Puppet** | User/group management, access matrix |
| **Export** | Dataset viewer with CSV download |
| **Playground** | Interactive AI agent testing |
| **Admin** | System configuration and monitoring |

---

## Zabbix Page

### Features
- Real-time problems dashboard
- Filter by severity, host group, acknowledgment status
- Host details panel
- Bulk acknowledge multiple problems

### Filters
- Severity levels (Information → Disaster)
- Host groups
- Show/hide acknowledged problems

---

## NetBox Page

### Features
- Live search against NetBox API
- Dataset selector: All / Devices / VMs
- Results link directly to NetBox objects

### Search
- Full-text search across all fields
- Results include devices, VMs, and IP addresses (when "All" selected)

---

## Jira Page

### Features
- Issue search with multiple filters
- Click issue key to open in Jira
- Read-only view

### Filters
- Search text (full-text)
- Project
- Status
- Assignee
- Priority
- Type
- Team (Service Desk)
- Updated date range
- Max results
- Open issues only

---

## Confluence Page

### Features
- CQL-based content search
- Click title to open in Confluence
- Read-only view

### Filters
- Search text
- Space (key or exact name)
- Content type
- Labels
- Updated date range
- Max results

---

## Foreman Page

### Features
- Host inventory table
- Multi-instance support (tabs)
- Real-time search
- Manual cache refresh
- Cache status display

### Columns
- Name
- Operating System
- Environment
- Compute/Model
- Hostgroup
- Last Report

---

## Puppet Page

### Tabs

| Tab | Description |
|-----|-------------|
| **Users** | All users with UID, email, status, sudo, groups, auth |
| **Groups** | All groups with GID, member count |
| **Access Matrix** | User × Group membership grid |

### Features
- Search across all views
- Export to Excel (color-coded security warnings)
- Security analysis badges:
  - 🔐 SHA-512 — Strong password
  - 🔐 MD5 ⚠️ — Weak password
  - 🔑 RSA 4096b — Strong SSH key
  - 🔑 RSA 1024b ⚠️ — Weak SSH key
  - 🔑 ED25519 — Modern SSH key

---

## Export Page

### Dataset Tabs
- **Devices** — NetBox devices
- **VMs** — NetBox virtual machines
- **All** — Merged dataset

### Grid Features
- **Virtual scrolling** — Smooth with large datasets
- **Column management** — Drag-and-drop reorder, show/hide
- **Sorting** — Click header (Shift+click for multi-sort)
- **Per-column filters** — Filter each column independently
- **Quick search** — Filter across all fields
- **Density** — Compact / Comfortable modes
- **Download CSV** — Export filtered view

### Actions
- **Update dataset** — Runs export, shows live log
- **View logs** — Opens log panel

### Log Panel
- Resizable (drag corners)
- Smart autoscroll (stops when you scroll up)
- Press Esc to close

### Preferences
Per-dataset settings are remembered:
- Column order
- Column visibility
- Active filters

---

## Tasks Page

Located at `/app/#tasks`.

### Features
- Overview of all cached datasets
- Last update timestamps
- File presence indicators
- Individual refresh buttons
- Bulk "Update all" action

### Views
Toggle between:
- **Cards** — Tiled layout (default)
- **Rows** — Dense one-line view

### Dataset Details
- Click disclosure to see stdout/stderr from last refresh

---

## Playground Page

Located at `/app/#playground`.

The Agent Playground provides an interactive chat interface for testing AI agents.

### Features
- **Agent Selection**: Choose from Triage, Engineer, or Reviewer agents
- **Real-time Chat**: Streaming responses with tool call visibility
- **Session Persistence**: Chat history preserved across page reloads
- **Configuration Panel**: Adjust model, temperature, and enabled skills
- **Usage Display**: Token count and cost per session

### Agent Cards
Click an agent card to start chatting:
- **Triage** — Fast ticket analysis and categorization
- **Engineer** — Deep technical investigation
- **Reviewer** — Quality assurance and validation

### Chat Interface
- Type messages in the input field
- Press Enter or click Send to submit
- Tool calls appear as indicators during processing
- Responses stream in real-time

### Configuration
Expand the settings panel to configure:
- **Model**: haiku-4-5 / sonnet-4-5 / opus-4-5
- **Temperature**: 0.0 - 1.0
- **Skills**: Enable/disable specific integrations

See [Playground Documentation](playground.md) for detailed API reference.

---

## Admin Section

Access admin features at `/app/#admin`.

### Admin Tabs

| Tab | Description |
|-----|-------------|
| **vCenter** | Manage vCenter instance configurations |
| **Foreman** | Manage Foreman instance configurations |
| **Puppet** | Manage Puppet repository configurations |
| **Modules** | View and manage enabled modules |
| **AI Providers** | Configure AI providers and test connections |
| **AI Usage** | Monitor AI token usage and costs |
| **Playground** | View playground usage statistics |
| **RAG** | Manage knowledge base and vector store |

### vCenter Management
- Add/edit/delete vCenter configurations
- Test connections
- View inventory statistics

### Foreman Management
- Configure multiple Foreman instances
- Set credentials and sync settings

### Puppet Management
- Configure Puppet repositories
- Set up SSH access for data retrieval

### Module Management
- View all available modules
- Enable/disable modules
- Check module health status
- View missing dependencies

### AI Providers
- Configure provider credentials
- Test provider connectivity
- Set default models per provider

### AI Usage Dashboard
- Total requests, tokens, and costs
- Usage breakdown by model
- Activity logs with filtering

### Playground Usage

Monitor playground usage:

- **Overview Cards**: Total requests, tokens, costs, unique users
- **Users Table**: Per-user usage with columns:
  - Username
  - Requests count
  - Total tokens
  - Cost (USD)
  - Last active
- **Recent Activity**: Live log showing:
  - Time
  - User
  - Client (web/telegram/slack/teams)
  - Agent
  - Model
  - Tokens
  - Cost

### RAG / Knowledge Base
- View indexed document count
- Manage Confluence spaces
- Trigger reindexing
- Check embedding status

---

## Branding

To display a custom logo:

1. Add `logo.png` to `src/infrastructure_atlas/api/static/`
2. The login page and top bar will show the logo
3. If absent, only the product name is displayed

---

## Related Documentation

- [Getting Started](getting-started.md) — Installation and setup
- [API Reference](api-reference.md) — REST endpoints
- [CLI Reference](cli-reference.md) — Command-line interface
- [Agent Playground](playground.md) — Interactive agent testing
- [Bot System](bots.md) — Telegram, Slack, Teams integration
- [AI Chat System](ai-chat.md) — Multi-provider AI configuration
