# Jira Integration

Infrastructure Atlas integrates with Jira for issue search and tracking.

## Configuration

### Required Environment Variables

```env
ATLASSIAN_BASE_URL=https://your-domain.atlassian.net
ATLASSIAN_EMAIL=your-email@example.com
ATLASSIAN_API_TOKEN=your-api-token
```

### Legacy Fallback (Deprecated)

```env
JIRA_BASE_URL=https://your-domain.atlassian.net
JIRA_EMAIL=your-email@example.com
JIRA_API_TOKEN=your-api-token
```

## CLI Commands

### Search

```bash
uv run atlas jira search [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--q` | Search text |
| `--jql` | Raw JQL query |
| `--project` | Project key |
| `--status` | Issue status |
| `--assignee` | Assignee username |
| `--priority` | Priority level |
| `--type` | Issue type |
| `--team` | Service Desk team |
| `--updated` | Updated since (e.g., `-30d`) |
| `--open` / `--all` | Open issues only / all issues |
| `--max` | Max results |

### Examples

```bash
# Basic search
uv run atlas jira search --q "router"

# Project with filters
uv run atlas jira search --project ABC --updated -30d --open

# Complex query
uv run atlas jira search --project OPS --status "In Progress" --assignee john --type Bug
```

## API Endpoints

### GET /jira/search

Search Jira issues with filtering.

| Parameter | Description |
|-----------|-------------|
| `q` | Search text |
| `project` | Project key |
| `status` | Issue status |
| `max` | Max results |

## Web UI

The **Jira** page (`/app/#jira`) provides:

### Features

- Full-text search across issues
- Multiple filter options
- Click issue key to open in Jira
- Read-only view

### Filters

| Filter | Description |
|--------|-------------|
| **Search** | Full-text search |
| **Project** | Project key |
| **Status** | Issue status |
| **Assignee** | Assigned user |
| **Priority** | Priority level |
| **Type** | Issue type |
| **Team** | Service Desk team |
| **Updated** | Date range |
| **Max** | Result limit |
| **Open only** | Toggle for open issues |

### Display

Results show:
- Issue key (linked to Jira)
- Summary
- Status
- Assignee
- Priority
- Updated date

## JQL Support

Use `--jql` for complex queries:

```bash
uv run atlas jira search --jql "project = ABC AND status = Open AND created >= -7d"
```

JQL takes precedence over other filter options when specified.

## Related Documentation

- [Configuration](../configuration.md) — Environment variables
- [CLI Reference](../cli-reference.md) — Complete command guide
- [Confluence Integration](confluence.md) — Atlassian ecosystem
