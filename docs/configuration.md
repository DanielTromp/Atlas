# Configuration

Infrastructure Atlas is configured through environment variables in a `.env` file.

## Quick Setup

```bash
cp .env.example .env
# Edit .env with your credentials
```

The CLI automatically loads `.env` from the project root. Use `--override-env` to force override existing environment variables.

## Core Settings

### Security

| Variable | Required | Description |
|----------|----------|-------------|
| `ATLAS_SECRET_KEY` | No | Fernet key (base64, 32 bytes) for encrypted secret store |
| `ATLAS_API_TOKEN` | No | Bearer token for API authentication |
| `ATLAS_UI_PASSWORD` | No | Password for web UI login |
| `ATLAS_UI_SECRET` | No | Session secret (auto-generated if not set) |

### SSL/TLS

| Variable | Required | Description |
|----------|----------|-------------|
| `ATLAS_SSL_CERTFILE` | No | Path to SSL certificate |
| `ATLAS_SSL_KEYFILE` | No | Path to SSL private key |
| `ATLAS_SSL_KEY_PASSWORD` | No | Password for encrypted SSL key |

### Logging

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `warning` | API/Uvicorn log level |
| `ATLAS_LOG_LEVEL` | `info` | CLI/background task log level |
| `ATLAS_LOG_STRUCTURED` | `false` | Enable structured JSON logging |

### Data Storage

| Variable | Default | Description |
|----------|---------|-------------|
| `NETBOX_DATA_DIR` | `data/` | Output directory for CSV/Excel exports |

## Integration Credentials

### NetBox

| Variable | Required | Description |
|----------|----------|-------------|
| `NETBOX_URL` | **Yes** | NetBox instance URL |
| `NETBOX_TOKEN` | **Yes** | API token |
| `NETBOX_EXTRA_HEADERS` | No | Additional headers (`Key1=val;Key2=val`) |

### Atlassian (Jira & Confluence)

| Variable | Required | Description |
|----------|----------|-------------|
| `ATLASSIAN_BASE_URL` | **Yes** | Atlassian Cloud URL (`https://your-domain.atlassian.net`) |
| `ATLASSIAN_EMAIL` | **Yes** | Account email |
| `ATLASSIAN_API_TOKEN` | **Yes** | API token |

Legacy fallback (deprecated):
- `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`

### Confluence Publishing

| Variable | Required | Description |
|----------|----------|-------------|
| `CONFLUENCE_CMDB_PAGE_ID` | No | Page ID for CMDB Excel attachment |
| `CONFLUENCE_DEVICES_PAGE_ID` | No | Page ID for devices table |
| `CONFLUENCE_VMS_PAGE_ID` | No | Page ID for VMs table |
| `CONFLUENCE_ENABLE_TABLE_FILTER` | No | Enable Table Filter macro (`1`) |
| `CONFLUENCE_ENABLE_TABLE_SORT` | No | Enable Table Sort macro (`1`) |

### Commvault

| Variable | Required | Description |
|----------|----------|-------------|
| `COMMVAULT_BASE_URL` | **Yes** | Commvault API URL |
| `COMMVAULT_API_TOKEN` | **Yes** | API token |
| `COMMVAULT_VERIFY_TLS` | No | Verify TLS certificates (default: true) |
| `COMMVAULT_JOB_CACHE_TTL` | No | Job cache TTL in seconds (default: 600) |
| `COMMVAULT_JOB_CACHE_BUCKET_SECONDS` | No | Cache key bucketing (default: 300) |

### Zabbix

| Variable | Required | Description |
|----------|----------|-------------|
| `ZABBIX_URL` | **Yes** | Zabbix API URL |
| `ZABBIX_TOKEN` | **Yes** | API token |

## Secret Store

When `ATLAS_SECRET_KEY` is set, Atlas enables an encrypted secret store:

1. Secrets from `.env` are synchronized to the database (encrypted)
2. Missing `.env` entries are restored from the database
3. Provides secure credential storage for integrations

Generate a Fernet key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Example .env File

```env
# === Core ===
ATLAS_SECRET_KEY=your-fernet-key-here
ATLAS_API_TOKEN=your-api-token
ATLAS_UI_PASSWORD=your-ui-password

# === NetBox ===
NETBOX_URL=https://netbox.example.com
NETBOX_TOKEN=your-netbox-token
NETBOX_DATA_DIR=data/

# === Atlassian ===
ATLASSIAN_BASE_URL=https://your-domain.atlassian.net
ATLASSIAN_EMAIL=your-email@example.com
ATLASSIAN_API_TOKEN=your-atlassian-token

# === Confluence Publishing ===
CONFLUENCE_CMDB_PAGE_ID=123456789
CONFLUENCE_DEVICES_PAGE_ID=987654321

# === Commvault ===
COMMVAULT_BASE_URL=https://commvault.example.com/api
COMMVAULT_API_TOKEN=your-commvault-token

# === Zabbix ===
ZABBIX_URL=https://zabbix.example.com/api_jsonrpc.php
ZABBIX_TOKEN=your-zabbix-token

# === Logging ===
LOG_LEVEL=warning
ATLAS_LOG_LEVEL=info
```

## Related Documentation

- [Getting Started](getting-started.md) — Installation and setup
- [CLI Reference](cli-reference.md) — Command-line options
- [API Reference](api-reference.md) — REST API endpoints
