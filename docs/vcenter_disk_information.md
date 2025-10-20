# vCenter VM Disk Information

## Overview

The vCenter integration includes comprehensive disk information for each virtual machine, providing insights into storage capacity, provisioning, and datastore locations.

## Features

### Disk Data Collection

For each VM, the system collects:

- **Disk Label**: Hardware identifier (e.g., "Hard disk 1")
- **Capacity**: Total disk capacity in bytes
- **Type**: Controller type (SCSI, IDE, SATA, NVMe)
- **Datastore**: Storage location
- **Thin Provisioning**: Whether the disk is thin or thick provisioned
- **Provisioned Bytes**: Actual storage consumed (for thick provisioned disks)
- **Disk Mode**: Persistence mode (persistent, independent, etc.)
- **Disk Path**: Full VMDK file path

### Aggregated Metrics

- **Total Disk Capacity**: Sum of all disk capacities for the VM
- **Total Provisioned**: Sum of actual storage provisioned on datastores

## Implementation Details

### Data Retrieval

Disk information is fetched using **pyVmomi (SOAP API)** as the primary method:

```python
# In vcenter_client.py
def get_vm_disks_vim(self, instance_uuid: str) -> list[Mapping[str, Any]]:
    """Get VM disk information using pyVmomi (SOAP API)."""
    # Connects to vCenter via pyVmomi
    # Retrieves disk devices from VM hardware configuration
    # Extracts controller type, capacity, backing info
    # Returns list of disk dictionaries
```

The REST API endpoint (`/rest/vcenter/vm/{vm}/hardware/disk`) is available as a fallback but provides limited information.

### Data Flow

1. **Fetch**: `VCenterClient.get_vm_disks_vim()` retrieves disk info for each VM
2. **Build**: `_build_vm()` processes disk data and calculates totals
3. **Serialize**: `_serialize_vm()` converts to JSON for cache storage
4. **Deserialize**: `_deserialize_vm()` loads from cache
5. **DTO**: `VCenterVMDTO` includes disk fields for API responses

### Caching

Disk information is cached along with other VM data in:
```
data/vcenter/{config_id}.json
```

Cache structure per VM:
```json
{
  "disks": [
    {
      "label": "Hard disk 1",
      "capacity_bytes": 32212254720,
      "type": "SCSI",
      "datastore": "Dorado-LUN2",
      "disk_path": "[Dorado-LUN2] vm-name/vm-name.vmdk",
      "thin_provisioned": false,
      "provisioned_bytes": 61298161326,
      "disk_mode": "persistent"
    }
  ],
  "total_disk_capacity_bytes": 32212254720,
  "total_provisioned_bytes": 61298161326
}
```

## Web UI Display

### VM Table View

The main VM table includes a **Disk** column showing total capacity:

```javascript
// In app.js
function formatVmDisks(vm) {
  const totalBytes = Number(vm?.total_disk_capacity_bytes);
  if (!Number.isFinite(totalBytes) || totalBytes <= 0) return '—';

  const gb = totalBytes / (1024 * 1024 * 1024);
  if (gb >= 10) {
    return `${Math.round(gb)} GB`;
  }
  const formatted = gb.toFixed(1).replace(/\.0$/, '');
  return `${formatted} GB`;
}
```

Example display: **"30 GB"**, **"500 GB"**, **"1024 GB"**

### VM Detail Page

The detail page shows a **Disks** section with a table containing:

| Column | Description |
|--------|-------------|
| Label | Disk hardware label |
| Capacity | Formatted capacity (e.g., "30.00 GB") |
| Type | Controller type (SCSI/IDE/SATA/NVMe) |
| Datastore | Storage location |
| Thin Provisioned | Yes/No |

The section is only shown if the VM has at least one disk.

## Performance Considerations

### Fetch Time

- Disk information adds approximately **50-100ms per VM** to the refresh time
- For 410 VMs: adds ~20-40 seconds to full refresh
- Partial updates (`--vm` flag) include disk fetching

### Optimization

Disk data is always fetched as it's considered essential VM information. To optimize:

1. Use partial VM updates for single VM changes
2. Schedule full refreshes during off-peak hours
3. pyVmomi connection is reused across all VMs in a single refresh

## CLI Usage

### Full Refresh (includes disks)

```bash
uv run atlas vcenter refresh --id {config_id}
```

### Single VM Refresh (includes disks)

```bash
uv run atlas vcenter refresh --id {config_id} --vm {vm_id}
```

### View Disk Data in Cache

```bash
# View all disk data for a VM
jq '.vms[] | select(.vm_id == "vm-69696") | .disks' \
  data/vcenter/{config_id}.json

# View total capacities
jq '.vms[] | select(.vm_id == "vm-69696") |
  {name, total_disk_capacity_bytes, total_provisioned_bytes}' \
  data/vcenter/{config_id}.json
```

## API Endpoints

### Get VMs with Disk Info

```http
GET /api/vcenter/{config_id}/vms
```

Response includes disk fields:
```json
{
  "vms": [
    {
      "id": "vm-69696",
      "name": "sa-mgmt-tools-prod1",
      "disks": [...],
      "total_disk_capacity_bytes": 32212254720,
      "total_provisioned_bytes": 61298161326
    }
  ]
}
```

## Use Cases

### Storage Planning

- Identify VMs with high disk capacity
- Track thin vs thick provisioned disks
- Monitor datastore usage per VM

### Capacity Analysis

```bash
# Find VMs over 500GB
jq '.vms[] | select(.total_disk_capacity_bytes > 536870912000) |
  {name, capacity_gb: (.total_disk_capacity_bytes / 1073741824)}' \
  data/vcenter/{config_id}.json
```

### Thin Provisioning Report

```bash
# Find all thin provisioned VMs
jq '.vms[] | select(.disks | any(.thin_provisioned == true)) |
  {name, disks: [.disks[] | select(.thin_provisioned == true) | .label]}' \
  data/vcenter/{config_id}.json
```

## Troubleshooting

### Disk Data Not Appearing

1. **Check pyVmomi connection**: Disk data requires pyVmomi connectivity
2. **Verify instance_uuid**: VMs must have instance_uuid for pyVmomi lookup
3. **Check permissions**: vCenter account needs VM hardware read permissions
4. **Refresh data**: Use `--vm` flag to update specific VM

### Missing Disk Type

The controller type detection may not work for all disk types. This doesn't affect capacity or datastore information.

### Zero Total Capacity

If `total_disk_capacity_bytes` is null/zero:
- Check if disk capacity fields are present in cache
- Verify pyVmomi is returning `capacityInBytes` or `capacityInKB`
- Check for VM hardware compatibility

## Related Documentation

- [vCenter Integration Architecture](architecture_overview.md)
- [Performance Benchmarks](performance_benchmarks.md)
- [API Documentation](../README.md#api-endpoints)

## Future Enhancements

Potential improvements:
- Disk usage percentage (requires guest tools)
- Historical capacity trends
- Datastore-level aggregation
- Disk I/O statistics
- Reclaim recommendations for thin provisioned disks
