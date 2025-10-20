# Master Database Schema

## Overview

The master database uses a generic device model that can represent infrastructure components from any source system (vCenter, Foreman, Oxidized, storage systems, etc.). This allows unified querying, tracking, and synchronization across all infrastructure services.

## Design Principles

1. **Source Agnostic**: Generic fields work for all device types
2. **Extensible**: JSON metadata for source-specific fields
3. **Traceable**: Track data source and freshness
4. **Relational**: Link devices to each other (VM→Host, Interface→Device)
5. **Auditable**: Full history of all changes

## Core Tables

### devices

Central table for all infrastructure devices regardless of source.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment ID |
| name | TEXT NOT NULL | Device name/hostname |
| device_type | TEXT NOT NULL | Type: server, vm, network_device, storage, container |
| source_system | TEXT NOT NULL | Origin: vcenter, foreman, oxidized, dorado, netapp, etc. |
| source_id | TEXT NOT NULL | ID in source system (e.g., vm-69696) |
| status | TEXT | active, inactive, unknown |
| metadata | TEXT | JSON blob for source-specific fields |
| first_seen | TIMESTAMP | When first discovered |
| last_seen | TIMESTAMP | Last confirmed existence |
| created_at | TIMESTAMP | Record creation time |
| updated_at | TIMESTAMP | Last update time |

**Indexes**:
- UNIQUE(source_system, source_id)
- INDEX(device_type)
- INDEX(name)
- INDEX(status)
- INDEX(last_seen)

**Example metadata JSON**:
```json
{
  "vcenter": {
    "power_state": "POWERED_ON",
    "guest_os": "Ubuntu 22.04",
    "cpu_count": 4,
    "memory_mb": 8192,
    "cluster": "Production",
    "host": "esxi-prod-01.example.com"
  }
}
```

### device_relationships

Tracks connections between devices (VM→Host, Server→Switch, Volume→Array).

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment ID |
| parent_device_id | INTEGER | Parent device (e.g., ESXi host) |
| child_device_id | INTEGER | Child device (e.g., VM) |
| relationship_type | TEXT | hosts, connects_to, backs_up, manages |
| metadata | TEXT | JSON for relationship-specific data |
| created_at | TIMESTAMP | When relationship discovered |
| updated_at | TIMESTAMP | Last confirmed |

**Foreign Keys**:
- parent_device_id → devices(id) ON DELETE CASCADE
- child_device_id → devices(id) ON DELETE CASCADE

**Indexes**:
- INDEX(parent_device_id)
- INDEX(child_device_id)
- INDEX(relationship_type)

**Example**:
```
parent: esxi-prod-01 (device_type=server, source=vcenter)
child: sa-mgmt-tools-prod1 (device_type=vm, source=vcenter)
relationship_type: hosts
```

### sync_metadata

Tracks sync status and data freshness per source system.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment ID |
| source_system | TEXT NOT NULL | vcenter, foreman, oxidized, etc. |
| source_identifier | TEXT | Config ID or instance identifier |
| last_sync_start | TIMESTAMP | When sync began |
| last_sync_complete | TIMESTAMP | When sync finished successfully |
| last_sync_status | TEXT | success, failed, partial |
| sync_duration_seconds | REAL | How long sync took |
| devices_added | INTEGER | New devices found |
| devices_updated | INTEGER | Existing devices modified |
| devices_removed | INTEGER | Devices marked inactive |
| error_message | TEXT | Error details if failed |
| created_at | TIMESTAMP | First sync time |
| updated_at | TIMESTAMP | Last update |

**Indexes**:
- UNIQUE(source_system, source_identifier)
- INDEX(last_sync_complete)

## Device Type-Specific Tables

### vms

Extended VM information (links to devices table).

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment ID |
| device_id | INTEGER NOT NULL | Foreign key to devices |
| instance_uuid | TEXT | vCenter instance UUID |
| guest_os | TEXT | Operating system |
| cpu_count | INTEGER | Number of vCPUs |
| memory_mb | INTEGER | Memory in MB |
| power_state | TEXT | POWERED_ON, POWERED_OFF, SUSPENDED |
| tools_running | BOOLEAN | VMware tools status |
| ip_addresses | TEXT | JSON array of IPs |
| disks | TEXT | JSON array of disk info |
| snapshots | TEXT | JSON array of snapshots |
| total_disk_capacity_bytes | INTEGER | Sum of all disk capacity |
| total_snapshot_size_bytes | INTEGER | Sum of all snapshot sizes |

**Foreign Keys**:
- device_id → devices(id) ON DELETE CASCADE

**Indexes**:
- UNIQUE(device_id)
- INDEX(instance_uuid)
- INDEX(power_state)

### network_interfaces

Network interfaces for any device type.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment ID |
| device_id | INTEGER NOT NULL | Foreign key to devices |
| interface_name | TEXT NOT NULL | eth0, vmnic0, Management1, etc. |
| mac_address | TEXT | MAC address |
| ip_addresses | TEXT | JSON array of IPs |
| speed_mbps | INTEGER | Interface speed |
| status | TEXT | up, down, disabled |
| interface_type | TEXT | physical, virtual, loopback |
| metadata | TEXT | JSON for source-specific fields |

**Foreign Keys**:
- device_id → devices(id) ON DELETE CASCADE

**Indexes**:
- INDEX(device_id)
- INDEX(mac_address)
- INDEX(status)

### storage_volumes

Storage volumes from any source (Dorado, NetApp, vCenter datastores).

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment ID |
| device_id | INTEGER | Optional link to device if volume is a device |
| source_system | TEXT NOT NULL | dorado, netapp, vcenter |
| source_id | TEXT NOT NULL | Volume ID in source |
| name | TEXT NOT NULL | Volume/LUN name |
| volume_type | TEXT | lun, filesystem, datastore, qtree |
| capacity_bytes | INTEGER | Total capacity |
| used_bytes | INTEGER | Used space |
| storage_array | TEXT | Parent array/filer name |
| raid_level | TEXT | RAID 5, RAID 10, etc. |
| thin_provisioned | BOOLEAN | Thin vs thick |
| metadata | TEXT | JSON for source-specific fields |
| created_at | TIMESTAMP | Volume creation time |
| updated_at | TIMESTAMP | Last update |

**Indexes**:
- UNIQUE(source_system, source_id)
- INDEX(device_id)
- INDEX(storage_array)
- INDEX(volume_type)

### device_configs

Configuration files from Oxidized and similar tools.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment ID |
| device_id | INTEGER NOT NULL | Foreign key to devices |
| config_text | TEXT | Full configuration |
| config_hash | TEXT | SHA256 hash for change detection |
| version | INTEGER | Version number |
| retrieved_at | TIMESTAMP | When config was fetched |
| source_system | TEXT | oxidized, puppet, etc. |

**Foreign Keys**:
- device_id → devices(id) ON DELETE CASCADE

**Indexes**:
- INDEX(device_id, version DESC)
- INDEX(config_hash)
- INDEX(retrieved_at DESC)

### server_facts

Puppet/Foreman facts for servers.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment ID |
| device_id | INTEGER NOT NULL | Foreign key to devices |
| fact_name | TEXT NOT NULL | processors, memory, kernel, uptime, etc. |
| fact_value | TEXT | Value (can be JSON for complex facts) |
| collected_at | TIMESTAMP | When fact was collected |

**Foreign Keys**:
- device_id → devices(id) ON DELETE CASCADE

**Indexes**:
- INDEX(device_id, fact_name)
- INDEX(fact_name)

## Knowledge Base Tables

### kb_articles

Cached Confluence pages.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment ID |
| source_id | TEXT NOT NULL | Confluence page ID |
| space_key | TEXT | Space identifier |
| title | TEXT NOT NULL | Page title |
| body_text | TEXT | Plain text content for AI |
| body_html | TEXT | HTML content for display |
| url | TEXT | Full Confluence URL |
| parent_id | TEXT | Parent page ID |
| labels | TEXT | JSON array of labels |
| created_at | TIMESTAMP | Page creation time |
| last_updated | TIMESTAMP | Last modification in Confluence |
| cached_at | TIMESTAMP | When cached locally |

**Indexes**:
- UNIQUE(source_id)
- INDEX(space_key)
- INDEX(title)
- INDEX(last_updated DESC)

### issues

Cached Jira issues.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment ID |
| issue_key | TEXT NOT NULL | JIRA-123 |
| project_key | TEXT | Project identifier |
| issue_type | TEXT | Bug, Task, Story, Incident |
| summary | TEXT | Issue title |
| description | TEXT | Full description |
| status | TEXT | Open, In Progress, Resolved, Closed |
| resolution | TEXT | Fixed, Won't Fix, Duplicate, etc. |
| assignee | TEXT | Assigned user |
| reporter | TEXT | Reporter user |
| priority | TEXT | High, Medium, Low |
| labels | TEXT | JSON array of labels |
| comments | TEXT | JSON array of comments |
| created_at | TIMESTAMP | Issue creation |
| updated_at | TIMESTAMP | Last update |
| resolved_at | TIMESTAMP | Resolution time |
| cached_at | TIMESTAMP | When cached locally |

**Indexes**:
- UNIQUE(issue_key)
- INDEX(project_key)
- INDEX(status)
- INDEX(resolution)
- INDEX(resolved_at DESC)

### embeddings

Vector embeddings for semantic search.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment ID |
| content_type | TEXT NOT NULL | kb_article, issue, device |
| content_id | INTEGER NOT NULL | ID in source table |
| chunk_index | INTEGER | Chunk number for long content |
| text_content | TEXT | Text that was embedded |
| embedding_vector | BLOB | Serialized numpy array or JSON |
| embedding_model | TEXT | Model used (e.g., all-MiniLM-L6-v2) |
| created_at | TIMESTAMP | When embedding generated |

**Indexes**:
- INDEX(content_type, content_id)
- INDEX(embedding_model)

**Note**: For better vector search performance, consider migrating to pgvector (PostgreSQL) or using a dedicated vector database like Qdrant/Milvus in the future.

## Audit Tables

### sync_history

Complete audit trail of all sync operations.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment ID |
| sync_id | TEXT NOT NULL | Unique ID for this sync run |
| source_system | TEXT NOT NULL | Which system was synced |
| source_identifier | TEXT | Config ID or instance |
| operation | TEXT | add, update, delete, sync |
| device_id | INTEGER | Device affected (if applicable) |
| change_type | TEXT | device, config, relationship, etc. |
| old_value | TEXT | JSON of previous state |
| new_value | TEXT | JSON of new state |
| performed_by | TEXT | User or system that initiated |
| performed_at | TIMESTAMP | When change occurred |
| metadata | TEXT | JSON for additional context |

**Indexes**:
- INDEX(sync_id)
- INDEX(source_system)
- INDEX(device_id)
- INDEX(performed_at DESC)

### netbox_sync_approvals

Track NetBox sync approvals and changes.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment ID |
| sync_batch_id | TEXT NOT NULL | Batch identifier |
| device_id | INTEGER | Device being synced |
| action | TEXT | create, update, delete |
| netbox_object_type | TEXT | device, interface, ip_address, etc. |
| netbox_object_id | INTEGER | NetBox object ID |
| proposed_changes | TEXT | JSON of changes to apply |
| approval_status | TEXT | pending, approved, rejected |
| approved_by | TEXT | User who approved |
| approved_at | TIMESTAMP | Approval time |
| applied_at | TIMESTAMP | When change was applied to NetBox |
| rollback_data | TEXT | JSON for rollback if needed |

**Indexes**:
- INDEX(sync_batch_id)
- INDEX(device_id)
- INDEX(approval_status)
- INDEX(approved_at DESC)

## Data Flow Examples

### Example 1: vCenter VM

```
1. VCenterSyncService fetches VM from vCenter API
2. Create device record:
   - name: "sa-mgmt-tools-prod1"
   - device_type: "vm"
   - source_system: "vcenter"
   - source_id: "vm-69696"
   - metadata: {vcenter: {power_state: "POWERED_ON", ...}}
3. Create vm record linked to device
4. Create device_relationships: VM → ESXi host
5. Update sync_metadata: last_sync_complete, devices_added++
6. Log to sync_history
```

### Example 2: Oxidized Network Device

```
1. OxidizedSyncService fetches device list
2. Create device record:
   - name: "core-switch-01"
   - device_type: "network_device"
   - source_system: "oxidized"
   - source_id: "core-switch-01"
   - metadata: {oxidized: {model: "Cisco Nexus 9000", ...}}
3. Fetch device config and store in device_configs
4. Create network_interfaces for each interface
5. Update sync_metadata
```

### Example 3: Cross-System Correlation

```
Device appears in multiple systems:
- Foreman: "web-prod-01" (device_type=server, source=foreman)
- Puppet: "web-prod-01.example.com" (facts in server_facts)
- vCenter: "web-prod-01" (device_type=vm, source=vcenter)

Correlation logic:
1. Match by name (normalized)
2. Create single device with primary source (e.g., Foreman)
3. Merge metadata from all sources
4. Create device_relationships to link Foreman server → vCenter VM
```

## Migration Strategy

### Phase 1 (Current)
- SQLite database
- JSON metadata for flexibility
- Simple vector storage in BLOB

### Phase 2 (Future, if needed)
- Migrate to PostgreSQL
- Use pgvector for embeddings
- Better full-text search with pg_trgm
- Partitioning for large tables (sync_history)

## Maintenance

### Cleanup Old Data
```sql
-- Remove stale devices (not seen in 90 days)
UPDATE devices
SET status = 'inactive'
WHERE last_seen < datetime('now', '-90 days')
  AND status = 'active';

-- Clean old sync history (keep 1 year)
DELETE FROM sync_history
WHERE performed_at < datetime('now', '-1 year');

-- Clean old device configs (keep last 10 versions per device)
DELETE FROM device_configs
WHERE id IN (
  SELECT id FROM (
    SELECT id, ROW_NUMBER() OVER (PARTITION BY device_id ORDER BY version DESC) as rn
    FROM device_configs
  ) WHERE rn > 10
);
```

### Performance Optimization
```sql
-- Rebuild indexes periodically
REINDEX;

-- Analyze tables for query optimization
ANALYZE;

-- Vacuum to reclaim space
VACUUM;
```

## Security Considerations

1. **No credentials in database**: All credentials stay in `.env` or encrypted secret store
2. **Audit trail**: All changes tracked in sync_history
3. **Role-based access**: Future: add users table for web UI authentication
4. **Encryption at rest**: Consider encrypting sensitive metadata fields
5. **API authentication**: All API endpoints require authentication

## Related Documentation

- [Master Database Plan](master_database_plan.md) - Implementation roadmap
- [Architecture Overview](../CLAUDE.md#architecture) - Overall system design
- [vCenter Integration](vcenter_disk_information.md) - Example integration
