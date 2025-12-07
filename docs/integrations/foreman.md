# Foreman Integration

Infrastructure Atlas integrates with Foreman for host inventory management and Puppet configuration visibility.

## Configuration

### Setup via CLI

```bash
uv run atlas foreman create \
  --name "Production Foreman" \
  --url "https://foreman.example.com" \
  --username "api_user" \
  --token "your_personal_access_token" \
  --verify-ssl
```

Or use combined authentication:

```bash
uv run atlas foreman create \
  --name "Production Foreman" \
  --url "https://foreman.example.com" \
  --token "api_user:your_personal_access_token"
```

### Setup via Admin UI

1. Navigate to **Admin → Foreman** (`/app/#admin`)
2. Click **Add Foreman Configuration**
3. Fill in connection details

### Authentication

Foreman 1.24.3+ requires HTTP Basic Auth with a Personal Access Token (PAT).

Options:
- Provide `username` and `token` separately
- Provide combined as `username:token`

## CLI Commands

### List Configurations

```bash
uv run atlas foreman list
```

### List Hosts

```bash
uv run atlas foreman hosts [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--config-id` | Filter by configuration ID |
| `--search` | Filter by name, OS, or environment |

Displays: ID, Name, OS, Environment, Compute/Model, Hostgroup, Last Report

### Refresh Cache

```bash
uv run atlas foreman refresh --id <config-id>
```

Updates the JSON cache used by the web UI.

### Host Details

```bash
uv run atlas foreman show <host-id> [--config-id <id>]
```

### Puppet Commands

```bash
# Puppet classes assigned to host
uv run atlas foreman puppet-classes <host-id> [--config-id <id>]

# User-configurable parameters
uv run atlas foreman puppet-parameters <host-id> [--config-id <id>]

# Puppet facts
uv run atlas foreman puppet-facts <host-id> [--config-id <id>] [--search <query>]
```

## Cache Storage

Host inventories are cached under `data/foreman/<config-id>.json`.

- Web UI uses cached data for performance (handles 1000+ hosts)
- CLI commands fetch fresh data from API

## API Endpoints

### GET /foreman/configs

List Foreman configurations.

### GET /foreman/hosts

List hosts with optional filtering.

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

| Parameter | Description |
|-----------|-------------|
| `search` | Filter facts |

## Web UI

The **Foreman** page (`/app/#foreman`) provides:

### Features

- Read-only host inventory table
- Multi-instance support (tabs for each Foreman)
- Real-time search filtering
- Manual cache refresh button
- Cache status display (timestamp, host count)

### Columns

| Column | Description |
|--------|-------------|
| Name | Host FQDN |
| Operating System | OS name and version |
| Environment | Puppet environment |
| Compute/Model | Hardware type |
| Hostgroup | Foreman hostgroup |
| Last Report | Last Puppet report time |

## Puppet Integration

Foreman's Puppet integration provides visibility into:

| Type | Description |
|------|-------------|
| **Classes** | Puppet classes assigned to hosts |
| **Parameters** | User-configurable Puppet parameters |
| **Facts** | Puppet facts reported by hosts |
| **Status** | Puppet agent status and proxy info |

## Related Documentation

- [Configuration](../configuration.md) — Environment variables
- [CLI Reference](../cli-reference.md) — Complete command guide
- [Puppet Integration](puppet.md) — Puppet manifest parsing
