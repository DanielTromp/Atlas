# NetBox Integration

Infrastructure Atlas integrates with NetBox to provide device and VM inventory management.

## Configuration

### Required Environment Variables

```env
NETBOX_URL=https://netbox.example.com
NETBOX_TOKEN=your-api-token-here
```

### Optional Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NETBOX_DATA_DIR` | `data/` | Output directory for exports |
| `NETBOX_EXTRA_HEADERS` | — | Additional headers (`Key1=val;Key2=val`) |

## CLI Commands

### Status Check

```bash
uv run atlas status
```

Verifies API connectivity and token validity.

### Export Commands

```bash
# Full export pipeline
uv run atlas export update --force

# Individual exports
uv run atlas export devices [--force]
uv run atlas export vms [--force]
uv run atlas export merge
uv run atlas export cache
```

### Export Options

| Option | Description |
|--------|-------------|
| `--force` | Re-fetch all data from NetBox |
| `--no-refresh-cache` | Reuse existing JSON snapshot |
| `--queue` | Execute via job runner |

### Output Files

| File | Description |
|------|-------------|
| `netbox_devices_export.csv` | Devices export |
| `netbox_vms_export.csv` | VMs export |
| `netbox_merged_export.csv` | Combined dataset |
| `Systems CMDB.xlsx` | Excel workbook |
| `netbox_cache.json` | JSON cache snapshot |

### Search

```bash
# Live search against NetBox API
uv run atlas netbox search --q "edge01" --dataset devices --limit 25
```

| Option | Default | Description |
|--------|---------|-------------|
| `--q` | — | Search query |
| `--dataset` | `all` | `all`, `devices`, or `vms` |
| `--limit` | `25` | Max results (0 = unlimited) |

### Device Details

```bash
# By ID
uv run atlas netbox device-json --id 1202

# By name
uv run atlas netbox device-json --name edge01 --raw
```

## API Endpoints

### GET /devices

Returns devices from CSV export.

### GET /vms

Returns VMs from CSV export.

### GET /all

Returns merged dataset.

### Query Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `limit` | `100` | Results per page (1–1000) |
| `offset` | `0` | Skip N results |
| `order_by` | — | Sort column |
| `order_dir` | `asc` | Sort direction |

## Web UI

The **NetBox** page (`/app/#netbox`) provides:

- Live search against NetBox API
- Dataset selector (All / Devices / VMs)
- Direct links to NetBox objects
- Results include devices, VMs, and IP addresses

The **Export** page (`/app/#export`) provides:

- Virtual scrolling grid for large datasets
- Column drag-and-drop reorder
- Per-column and global filters
- CSV download

## Caching

### JSON Cache

`netbox_cache.json` stores the latest snapshot with:
- Per-record hashes
- Metadata for change detection
- Timestamp information

### In-Memory TTL Cache

Named caches (`netbox.devices`, `netbox.vms`) provide per-process caching:

```bash
# View cache statistics
uv run atlas cache-stats [--json --include-empty --prime-netbox]
```

## Data Flow

```
NetBox API
    ↓
devices export → netbox_devices_export.csv
vms export     → netbox_vms_export.csv
    ↓
merge script   → netbox_merged_export.csv
               → Systems CMDB.xlsx
    ↓
(optional) Confluence publish
```

## Column Order

Export column order is determined by:

1. `NETBOX_DATA_DIR/Systems CMDB.xlsx` (sheet 1, row 1) — if present
2. Merged CSV header order — fallback
3. Unknown columns appended at end

## Related Documentation

- [Configuration](../configuration.md) — Environment variables
- [CLI Reference](../cli-reference.md) — Complete command guide
- [Confluence Integration](confluence.md) — Publishing exports
