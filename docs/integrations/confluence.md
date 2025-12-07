# Confluence Integration

Infrastructure Atlas integrates with Confluence for content search and automated CMDB publishing.

## Configuration

### Required Environment Variables

```env
ATLASSIAN_BASE_URL=https://your-domain.atlassian.net
ATLASSIAN_EMAIL=your-email@example.com
ATLASSIAN_API_TOKEN=your-api-token
```

### Publishing Variables

| Variable | Description |
|----------|-------------|
| `CONFLUENCE_CMDB_PAGE_ID` | Page ID for CMDB Excel attachment |
| `CONFLUENCE_DEVICES_PAGE_ID` | Page ID for devices table |
| `CONFLUENCE_VMS_PAGE_ID` | Page ID for VMs table |
| `CONFLUENCE_ENABLE_TABLE_FILTER` | Enable Table Filter macro (`1`) |
| `CONFLUENCE_ENABLE_TABLE_SORT` | Enable Table Sort macro (`1`) |

## CLI Commands

### Search

```bash
uv run atlas confluence search [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--q` | Search text |
| `--space` | Space key or exact name (comma-separated) |
| `--type` | Content type (page, blogpost, etc.) |
| `--updated` | Updated since (e.g., `-90d`) |
| `--max` | Max results |

### Examples

```bash
# Search in a specific space
uv run atlas confluence search --q "vm" --space "Operations - Network" --type page --updated -90d --max 50

# Search multiple spaces
uv run atlas confluence search --q "backup" --space "IT,Operations"
```

### Upload Attachment

```bash
uv run atlas confluence upload --file <path> [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--file` | File to upload (required) |
| `--page-id` | Target page ID (defaults to `CONFLUENCE_CMDB_PAGE_ID`) |
| `--name` | Attachment name override |
| `--comment` | Version comment |

### Publish CMDB

```bash
uv run atlas confluence publish-cmdb
```

Uploads the Systems CMDB Excel to the configured page.

### Publish Tables

```bash
# Devices table
uv run atlas confluence publish-devices-table [--filter] [--sort]

# VMs table
uv run atlas confluence publish-vms-table [--filter] [--sort]
```

| Option | Description |
|--------|-------------|
| `--filter` | Enable Table Filter macro |
| `--sort` | Enable Table Sort macro |

**Note:** Table macros require the Table Filter & Charts app in Confluence.

## Auto-Publishing

When Confluence variables are configured, `uv run atlas export update`:

1. Exports NetBox data
2. Automatically uploads CMDB Excel
3. Refreshes Confluence tables

## API Endpoints

### GET /confluence/search

Search Confluence content using CQL.

| Parameter | Description |
|-----------|-------------|
| `q` | Search text |
| `space` | Space key or name |
| `type` | Content type |
| `max` | Max results |

## Web UI

The **Confluence** page (`/app/#confluence`) provides:

- CQL-based content search
- Space filtering (key or exact name)
- Content type filtering
- Click title to open in Confluence
- Read-only view

### Filters

- **Search** — Full-text search
- **Space** — Space key or exact name
- **Type** — Content type
- **Labels** — Filter by labels
- **Updated** — Date range
- **Max** — Result limit

## Space Resolution

- Exact space names are resolved to keys
- Partial matches are not supported
- Multiple spaces can be comma-separated

## Column Order

Table columns respect `netbox-export/etc/column_order.xlsx` when present.

### Devices Table Columns

- Name
- Status
- Role
- IP Address
- OOB IP

### VMs Table Columns

- Name
- Status
- Cluster
- IP Address
- Device

## Related Documentation

- [Configuration](../configuration.md) — Environment variables
- [CLI Reference](../cli-reference.md) — Complete command guide
- [NetBox Integration](netbox.md) — Export source data
