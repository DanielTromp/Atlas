# Zabbix Integration

Infrastructure Atlas integrates with Zabbix for monitoring problems and host management.

## Configuration

### Required Environment Variables

```env
ZABBIX_URL=https://zabbix.example.com/api_jsonrpc.php
ZABBIX_TOKEN=your-api-token
```

## CLI Commands

### Problems

```bash
uv run atlas zabbix problems [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--limit` | Max problems to return |
| `--severities` | Comma-separated severity levels (e.g., `2,3,4`) |
| `--groupids` | Filter by host group IDs |
| `--all` | Include acknowledged problems |

### Dashboard

```bash
uv run atlas zabbix dashboard [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--systems-only` | Filter to systems |
| `--unack-only` | Unacknowledged problems only |
| `--json` | JSON output for automation |
| `--groupids` | Override host group IDs |
| `--hostids` | Filter by host IDs |
| `--severities` | Filter by severity levels |
| `--include-subgroups` | Include subgroups |
| `--no-include-subgroups` | Exclude subgroups |

### Examples

```bash
# View current problems
uv run atlas zabbix problems --limit 20 --severities 2,3,4

# Dashboard with filters
uv run atlas zabbix dashboard --systems-only --unack-only

# JSON output for scripts
uv run atlas zabbix dashboard --json
```

## Severity Levels

| Level | Name |
|-------|------|
| 0 | Not classified |
| 1 | Information |
| 2 | Warning |
| 3 | Average |
| 4 | High |
| 5 | Disaster |

## API Endpoints

### GET /zabbix/problems

Get current problems with optional filters.

### GET /zabbix/hosts

List monitored hosts.

### POST /zabbix/acknowledge

Bulk acknowledge problems.

**Request Body:**
```json
{
  "eventids": [12345, 67890],
  "message": "Acknowledged via Atlas"
}
```

## Web UI

The **Zabbix** page (`/app/#zabbix`) provides:

### Features

- Real-time problems dashboard
- Severity-based filtering
- Host group filtering
- Acknowledgment status toggle
- Host details panel
- Bulk acknowledge multiple problems

### Filtering

- **Severity** — Filter by severity levels
- **Host Groups** — Filter by Zabbix host groups
- **Acknowledged** — Show/hide acknowledged problems

### Actions

- Click a problem row to see details
- Select multiple problems for bulk acknowledge
- Click host name to view host details

## Related Documentation

- [Configuration](../configuration.md) — Environment variables
- [CLI Reference](../cli-reference.md) — Complete command guide
- [Web UI Guide](../web-ui.md) — Frontend features
