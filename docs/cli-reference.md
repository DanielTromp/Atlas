# CLI Reference

Infrastructure Atlas provides a comprehensive CLI via [Typer](https://typer.tiangolo.com/).

## Global Options

```bash
uv run atlas --help
uv run atlas <command> -h  # -h is an alias for --help
```

| Option | Description |
|--------|-------------|
| `--override-env` | Override existing environment variables from `.env` |
| `--help` / `-h` | Show help message |

---

## Status Check

```bash
uv run atlas status
```

Checks API connectivity and token validity.

---

## Export Commands

### Full Update

```bash
uv run atlas export update [OPTIONS]
```

Runs the complete export pipeline: devices → VMs → merge → Excel.

| Option | Description |
|--------|-------------|
| `--force` | Re-fetch all data from NetBox |
| `--no-refresh-cache` | Reuse existing JSON snapshot |
| `--queue` | Execute via in-memory job runner |

If Confluence is configured, automatically uploads CMDB and refreshes tables.

### Individual Exports

```bash
uv run atlas export devices [--force]
uv run atlas export vms [--force]
uv run atlas export merge
uv run atlas export cache
```

---

## API Server

```bash
uv run atlas api serve [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--host` | `127.0.0.1` | Bind address |
| `--port` | `8000` | Bind port |
| `--ssl-certfile` | — | Path to SSL certificate |
| `--ssl-keyfile` | — | Path to SSL private key |
| `--log-level` | `warning` | Uvicorn log level |

---

## NetBox Commands

### Search

```bash
uv run atlas netbox search --q "query" [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--q` | — | Search query (required) |
| `--dataset` | `all` | Dataset: `all`, `devices`, `vms` |
| `--limit` | `25` | Max results (0 = unlimited) |

### Device JSON

```bash
uv run atlas netbox device-json --id <id>
uv run atlas netbox device-json --name <name> [--raw]
```

---

## Commvault Commands

### Backups

```bash
uv run atlas commvault backups [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--client` | — | Filter by client name or ID |
| `--since` | `24h` | Look-back window (`Nh`, `Nd`, or ISO) |
| `--limit` | `100` | Max jobs (0 = API default) |
| `--retained` | — | Only retained jobs |
| `--refresh-cache` | — | Force fresh API call |
| `--json` | — | JSON output |
| `--export-csv` | — | Export to CSV |
| `--export-xlsx` | — | Export to Excel |
| `--out` | — | Output filename stem |

### Storage

```bash
uv run atlas commvault storage list
uv run atlas commvault storage show <pool-id> [--json]
```

---

## Zabbix Commands

### Problems

```bash
uv run atlas zabbix problems [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--limit` | Max problems |
| `--severities` | Comma-separated severity levels |
| `--groupids` | Filter by host group IDs |
| `--all` | Include acknowledged |

### Dashboard

```bash
uv run atlas zabbix dashboard [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--systems-only` | Filter to systems |
| `--unack-only` | Unacknowledged only |
| `--json` | JSON output |
| `--groupids` | Host group IDs |
| `--hostids` | Host IDs |
| `--severities` | Severity levels |
| `--include-subgroups` | Include subgroups |

---

## Jira Commands

```bash
uv run atlas jira search [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--q` | Search text |
| `--jql` | Raw JQL query |
| `--project` | Project key |
| `--status` | Issue status |
| `--assignee` | Assignee |
| `--priority` | Priority |
| `--type` | Issue type |
| `--team` | Service Desk team |
| `--updated` | Updated since (e.g., `-30d`) |
| `--open` / `--all` | Open issues only |
| `--max` | Max results |

---

## Confluence Commands

### Search

```bash
uv run atlas confluence search [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--q` | Search text |
| `--space` | Space key or name (comma-separated) |
| `--type` | Content type |
| `--updated` | Updated since |
| `--max` | Max results |

### Upload

```bash
uv run atlas confluence upload --file <path> [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--file` | File to upload (required) |
| `--page-id` | Target page ID |
| `--name` | Attachment name |
| `--comment` | Version comment |

### Publish

```bash
uv run atlas confluence publish-cmdb
uv run atlas confluence publish-devices-table [--filter] [--sort]
uv run atlas confluence publish-vms-table [--filter] [--sort]
```

---

## vCenter Commands

```bash
uv run atlas vcenter refresh [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--all` | Refresh all configurations |
| `--name` | Configuration name |
| `--id` | Configuration ID |
| `--vm` / `-V` | Limit to specific VM IDs |
| `--verbose` | Show placement coverage |

---

## Foreman Commands

```bash
uv run atlas foreman list                    # List configurations
uv run atlas foreman hosts [OPTIONS]         # List hosts
uv run atlas foreman refresh --id <id>       # Refresh cache
uv run atlas foreman show <host-id>          # Host details
uv run atlas foreman puppet-classes <id>     # Puppet classes
uv run atlas foreman puppet-parameters <id>  # Puppet parameters
uv run atlas foreman puppet-facts <id>       # Puppet facts
```

---

## Tasks Commands

```bash
uv run atlas tasks refresh [OPTIONS] [DATASETS...]
```

| Option | Description |
|--------|-------------|
| `--list` | List datasets and their status |
| `--dry-run` | Show commands without executing |

---

## Cross-System Search

```bash
uv run atlas search run --q "query" [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--q` | — | Search query (required) |
| `--zlimit` | `0` | Zabbix max items |
| `--jlimit` | `0` | Jira max issues |
| `--climit` | `0` | Confluence max results |
| `--json` | — | Full JSON output |
| `--out` | — | Save to file |

---

## Cache Statistics

```bash
uv run atlas cache-stats [--json] [--include-empty] [--prime-netbox]
```

---

## Related Documentation

- [Getting Started](getting-started.md) — Installation and setup
- [Configuration](configuration.md) — Environment variables
- [API Reference](api-reference.md) — REST endpoints
