# API Reference

Infrastructure Atlas exposes a REST API via FastAPI.

## Base URL

```
http://127.0.0.1:8000    # HTTP
https://127.0.0.1:8443   # HTTPS
```

## Authentication

### API (Bearer Token)

Set `ATLAS_API_TOKEN` in `.env` to require authentication:

```bash
curl -H "Authorization: Bearer $ATLAS_API_TOKEN" https://127.0.0.1:8443/devices
```

### Web UI (Session)

Set `ATLAS_UI_PASSWORD` to require login for `/app/*`.

- Login: `POST /auth/login`
- Session cookie: `atlas_ui`
- Authenticated sessions can call API endpoints without Bearer token

---

## Health & Status

### GET /health

Public endpoint for health checks.

**Response:**
```json
{
  "status": "ok",
  "netbox_data_dir": "/path/to/data",
  "csv_files": {
    "devices": true,
    "vms": true,
    "merged": true
  }
}
```

---

## NetBox Data Endpoints

### GET /devices

Returns devices from `netbox_devices_export.csv`.

### GET /vms

Returns VMs from `netbox_vms_export.csv`.

### GET /all

Returns merged dataset from `netbox_merged_export.csv`.

### Query Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `limit` | `100` | Results per page (1–1000) |
| `offset` | `0` | Skip N results |
| `order_by` | — | Column to sort by |
| `order_dir` | `asc` | Sort direction (`asc`/`desc`) |

**Example:**
```bash
curl "http://127.0.0.1:8000/devices?limit=5&order_by=Name&order_dir=desc"
```

### GET /column-order

Returns preferred column order from `Systems CMDB.xlsx`.

---

## Export Endpoints

### GET /export/stream

Streams live export output.

| Parameter | Values |
|-----------|--------|
| `dataset` | `devices`, `vms`, `all` |

**Example:**
```bash
curl -N "http://127.0.0.1:8000/export/stream?dataset=devices"
```

---

## Logs

### GET /logs/tail

Returns recent export log lines.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `n` | `200` | Number of lines (max 5000) |

**Response:**
```json
{
  "lines": [
    "2024-01-15 10:30:00 INFO Starting export...",
    "..."
  ]
}
```

---

## Commvault Endpoints

### GET /commvault/backups

Query backup jobs with filtering.

| Parameter | Description |
|-----------|-------------|
| `client` | Filter by client name/ID |
| `since` | Look-back window |
| `limit` | Max results |
| `retained` | Only retained jobs |

### GET /commvault/storage

List storage pools.

### GET /commvault/storage/{pool_id}

Get specific storage pool details.

---

## Zabbix Endpoints

### GET /zabbix/problems

Get current problems.

### GET /zabbix/hosts

List monitored hosts.

### POST /zabbix/acknowledge

Bulk acknowledge problems.

---

## Foreman Endpoints

### GET /foreman/configs

List Foreman configurations.

### GET /foreman/hosts

List hosts from Foreman.

| Parameter | Description |
|-----------|-------------|
| `config_id` | Configuration ID |
| `search` | Filter query |

### GET /foreman/hosts/{host_id}

Get host details.

### GET /foreman/hosts/{host_id}/puppet-classes

Get Puppet classes for host.

### GET /foreman/hosts/{host_id}/puppet-parameters

Get Puppet parameters for host.

### GET /foreman/hosts/{host_id}/puppet-facts

Get Puppet facts for host.

---

## Puppet Endpoints

### GET /puppet/configs

List Puppet repository configurations.

### GET /puppet/users

Get users from Puppet manifests.

| Parameter | Description |
|-----------|-------------|
| `config_id` | Configuration ID |

### GET /puppet/groups

Get groups from Puppet manifests.

### GET /puppet/export

Export Puppet data to Excel.

---

## Jira Endpoints

### GET /jira/search

Search Jira issues.

| Parameter | Description |
|-----------|-------------|
| `q` | Search text |
| `project` | Project key |
| `status` | Issue status |
| `max` | Max results |

---

## Confluence Endpoints

### GET /confluence/search

Search Confluence content.

| Parameter | Description |
|-----------|-------------|
| `q` | Search text |
| `space` | Space key |
| `type` | Content type |
| `max` | Max results |

---

## CORS

CORS is enabled for GET requests to allow local frontends.

## Data Normalization

- `NaN`, `NaT`, `±Inf` values are normalized to `null` in JSON responses

---

## Related Documentation

- [Getting Started](getting-started.md) — Installation and setup
- [CLI Reference](cli-reference.md) — Command-line interface
- [Configuration](configuration.md) — Environment variables
