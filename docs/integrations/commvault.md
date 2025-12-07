# Commvault Integration

Infrastructure Atlas integrates with Commvault for backup job monitoring and storage management.

## Configuration

### Required Environment Variables

```env
COMMVAULT_BASE_URL=https://commvault.example.com/api
COMMVAULT_API_TOKEN=your-api-token
```

### Optional Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `COMMVAULT_VERIFY_TLS` | `true` | Verify TLS certificates |
| `COMMVAULT_JOB_CACHE_TTL` | `600` | Job cache TTL in seconds |
| `COMMVAULT_JOB_CACHE_BUCKET_SECONDS` | `300` | Cache key bucketing |

## CLI Commands

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

### Examples

```bash
# Review recent jobs for a client
uv run atlas commvault backups --client core-prod3 --since 168h --limit 0

# Export retained jobs to Excel
uv run atlas commvault backups --since 0h --retained --export-xlsx --client cdr-prod

# JSON output with all metadata
uv run atlas commvault backups --client prod-server --json
```

### Storage

```bash
# List all storage pools
uv run atlas commvault storage list

# Get specific pool details
uv run atlas commvault storage show <pool-id> [--json]
```

## Cache Management

### Refresh Cache

Update the job cache without using the web UI:

```bash
uv run python scripts/update_commvault_cache.py --since 24 --limit 0
```

| Option | Description |
|--------|-------------|
| `--since` | Look-back hours (0 = keep all cached) |
| `--limit` | API request limit (0 = API decides) |
| `--skip-storage` | Only warm job cache |

### Cache Behavior

- Cache location: `data/commvault_backups.json` (~35MB)
- Subsequent runs pull only new + in-progress jobs
- CLI and web UI share the same cache

### In-Memory Cache

Per-client job metrics are cached with configurable TTL:

```bash
# Force refresh
uv run atlas commvault servers ... --refresh-cache
```

## API Endpoints

### GET /commvault/backups

Query backup jobs with filtering.

| Parameter | Description |
|-----------|-------------|
| `client` | Filter by client |
| `since` | Look-back window |
| `limit` | Max results |
| `retained` | Only retained jobs |

### GET /commvault/storage

List storage pools with capacity and status.

### GET /commvault/storage/{pool_id}

Get specific storage pool details.

## Output Format

### JSON Output

When using `--json`, output includes:

```json
{
  "source": "cache",
  "cache_generated_at": "2024-01-15T10:30:00Z",
  "jobs": [...],
  "export_paths": {
    "csv": "reports/backups.csv",
    "xlsx": "reports/backups.xlsx"
  }
}
```

### Export Files

| Format | Location | Description |
|--------|----------|-------------|
| CSV | `reports/<slug>.csv` | Comma-separated values |
| Excel | `reports/<slug>.xlsx` | Excel workbook |

Use `--out <stem>` to customize the filename.

## Web UI

The Tasks page (`/app/#tasks`) includes Commvault cache status:

- Last update timestamp
- File presence indicator
- Manual refresh button
- Computed lookback window

## Related Documentation

- [Configuration](../configuration.md) — Environment variables
- [CLI Reference](../cli-reference.md) — Complete command guide
- [Tasks Dashboard](../web-ui.md#tasks-page) — Web interface
