# vCenter Integration

Infrastructure Atlas integrates with VMware vCenter for VM inventory and placement visibility.

## Configuration

vCenter instances are configured through the web UI Admin section or CLI API.

### Setup via Admin UI

1. Navigate to **Admin → vCenter** (`/app/#admin`)
2. Click **Add vCenter Configuration**
3. Fill in:
   - **Name** — Display name (e.g., "Production vCenter")
   - **URL** — vCenter server URL
   - **Username** — Service account username
   - **Password** — Service account password
   - **Verify SSL** — Certificate verification toggle

### Credentials Storage

Credentials are stored encrypted in the database when `ATLAS_SECRET_KEY` is configured.

## CLI Commands

### Refresh Inventory

```bash
uv run atlas vcenter refresh [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--all` | Refresh all configured vCenters |
| `--name` | Refresh by configuration name |
| `--id` | Refresh by configuration ID |
| `--vm` / `-V` | Limit to specific VM IDs (repeatable) |
| `--verbose` | Show placement coverage details |

### Examples

```bash
# Refresh all vCenters
uv run atlas vcenter refresh --all --verbose

# Refresh by name
uv run atlas vcenter refresh --name "Production vCenter"

# Refresh by ID
uv run atlas vcenter refresh --id b55f0fa8-e253-4b5d-a0b6-8f9135bce4d8

# Debug specific VMs
uv run atlas vcenter refresh --id <config-id> --vm vm-1058 --vm vm-2045
```

### Verbose Output

With `--verbose`, the refresh shows:
- Placement coverage per vCenter
- Host/cluster/datacenter/resource pool/folder statistics
- Example VM when data is missing
- Raw placement payload for debugging

## Cache Storage

Inventories are cached under `data/vcenter/<config-id>.json`.

Each cache file contains:
- VM inventory
- Host placement data
- Cluster information
- Timestamp metadata

## Web UI

### vCenter View

Located at `/app/#vcenter` (when configured).

Features:
- VM inventory browser
- Placement coverage visualization
- Cluster/host/datastore views

### Admin Configuration

Located at **Admin → vCenter** (`/app/#admin`).

Actions:
- Add new vCenter configurations
- Edit existing configurations
- Delete configurations
- Test connectivity

## Placement Data

The integration tracks VM placement:

| Field | Description |
|-------|-------------|
| Host | ESXi host running the VM |
| Cluster | vSphere cluster |
| Datacenter | Datacenter location |
| Resource Pool | Resource allocation pool |
| Folder | VM folder path |

## Related Documentation

- [Configuration](../configuration.md) — Environment variables
- [CLI Reference](../cli-reference.md) — Complete command guide
- [Web UI Guide](../web-ui.md) — Frontend features
