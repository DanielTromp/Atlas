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

## Admin Section

Access admin features at `/app/#admin`.

### Available Configurations
- vCenter instances
- Foreman instances
- Puppet repositories

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
