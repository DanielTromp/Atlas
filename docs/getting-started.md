# Getting Started

This guide walks you through installing and configuring Infrastructure Atlas.

## Prerequisites

- **Python 3.11+**
- **[uv](https://github.com/astral-sh/uv)** — Fast Python package manager
- **Git** — For cloning the repository

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/your-org/infrastructure-atlas.git
cd infrastructure-atlas
```

### 2. Configure Environment

Copy the example environment file and edit it with your credentials:

```bash
cp .env.example .env
```

At minimum, configure these variables for NetBox:

```env
NETBOX_URL=https://netbox.example.com
NETBOX_TOKEN=your-api-token-here
```

See [Configuration](configuration.md) for all available options.

### 3. Verify Installation

```bash
# Check that the CLI is working
uv run atlas --help

# Test NetBox connectivity
uv run atlas status
```

## First Steps

### Start the Web UI

```bash
uv run atlas api serve --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000/app/](http://127.0.0.1:8000/app/) in your browser.

If you've set `ATLAS_UI_PASSWORD` in your `.env`, you'll be prompted to log in.

### Export NetBox Data

```bash
# Full export: devices → VMs → merge → Excel
uv run atlas export update --force
```

This creates:
- `data/netbox_devices_export.csv`
- `data/netbox_vms_export.csv`
- `data/netbox_merged_export.csv`
- `data/Systems CMDB.xlsx`

### Search Across Systems

```bash
# Cross-system search
uv run atlas search run --q "server-name" --json

# Search specific systems
uv run atlas netbox search --q "edge01" --dataset devices
uv run atlas jira search --q "network" --open
```

## HTTPS Setup (Optional)

For secure connections, generate local certificates:

### Quick Self-Signed (Development)

```bash
mkdir -p certs
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout certs/localhost-key.pem \
  -out certs/localhost.pem \
  -subj "/CN=localhost"
```

### Using mkcert (Trusted Locally)

```bash
# Install mkcert first: https://github.com/FiloSottile/mkcert
mkcert -key-file certs/localhost-key.pem \
       -cert-file certs/localhost.pem \
       localhost 127.0.0.1 ::1
```

### Run with HTTPS

```bash
uv run atlas api serve \
  --host 127.0.0.1 \
  --port 8443 \
  --ssl-certfile certs/localhost.pem \
  --ssl-keyfile certs/localhost-key.pem
```

Or set environment variables:

```env
ATLAS_SSL_CERTFILE=certs/localhost.pem
ATLAS_SSL_KEYFILE=certs/localhost-key.pem
```

## Next Steps

- [Configuration](configuration.md) — All environment variables
- [CLI Reference](cli-reference.md) — Complete command guide
- [Web UI Guide](web-ui.md) — Frontend features
- [API Reference](api-reference.md) — REST endpoints
