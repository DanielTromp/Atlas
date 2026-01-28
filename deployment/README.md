# Atlas Deployment Guide - sa-mgmt-tools-prod2

This guide deploys Atlas (production + development) on a server using Podman with HTTPS.

## Architecture

```
                         ┌─────────────────────────────────────────┐
                         │         sa-mgmt-tools-prod2             │
                         │                                         │
    HTTPS :443 ─────────►│  ┌─────────┐                            │
    (atlas.internal)     │  │ Traefik │──► Atlas Prod (:8000)      │
                         │  │  Proxy  │                            │
    HTTPS :8443 ────────►│  │         │──► Atlas Dev  (:8001)      │
    (atlas-dev.internal) │  └─────────┘                            │
                         │       │                                 │
                         │       ▼                                 │
                         │  ┌─────────┐    ┌─────────┐             │
                         │  │ MongoDB │    │ MongoDB │             │
                         │  │  Prod   │    │   Dev   │             │
                         │  │ (:27017)│    │ (:27018)│             │
                         │  └─────────┘    └─────────┘             │
                         │                                         │
                         │  /var/lib/data/                         │
                         │  ├── Atlas/      (production)           │
                         │  ├── Atlas-dev/  (development)          │
                         │  └── traefik/    (reverse proxy)        │
                         └─────────────────────────────────────────┘
```

## Directory Structure

```
/var/lib/data/
├── Atlas/                      # Production
│   ├── .env                    # Production secrets
│   ├── docker-compose.yml      # Prod compose (symlink or copy)
│   └── data/
│       ├── mongodb/            # MongoDB data
│       └── app/                # Atlas caches
│
├── Atlas-dev/                  # Development
│   ├── .env                    # Dev secrets (can differ)
│   ├── docker-compose.yml      # Dev compose
│   └── data/
│       ├── mongodb/            # Separate MongoDB
│       └── app/                # Dev caches
│
├── traefik/                    # Shared reverse proxy
│   ├── docker-compose.yml
│   ├── traefik.yml
│   ├── dynamic/
│   │   └── atlas.yml
│   └── certs/
│       ├── ca.crt              # CA cert (install in browsers)
│       ├── atlas.crt
│       └── atlas.key
│
└── scripts/
    ├── generate-certs.sh
    └── backup-mongodb.sh
```

---

## Step 1: Install Podman and Dependencies

```bash
# On RHEL/Rocky/Alma Linux 8/9:
sudo dnf install -y podman podman-compose

# On Ubuntu/Debian:
sudo apt-get update
sudo apt-get install -y podman podman-compose

# Verify installation
podman --version
podman-compose --version
```

## Step 2: Create Directory Structure

```bash
# Create base directories
sudo mkdir -p /var/lib/data/{Atlas,Atlas-dev,traefik}/{data,logs}
sudo mkdir -p /var/lib/data/Atlas/data/{mongodb,app}
sudo mkdir -p /var/lib/data/Atlas-dev/data/{mongodb,app}
sudo mkdir -p /var/lib/data/traefik/{certs,dynamic}
sudo mkdir -p /var/lib/data/scripts

# Set ownership (adjust user as needed)
sudo chown -R $(whoami):$(whoami) /var/lib/data/
```

## Step 3: Generate Self-Signed Certificates

```bash
# Copy the cert generation script
cp /var/lib/data/Atlas/deployment/scripts/generate-certs.sh /var/lib/data/scripts/
chmod +x /var/lib/data/scripts/generate-certs.sh

# Generate certificates (adjust domains as needed)
cd /var/lib/data/scripts
./generate-certs.sh atlas.internal atlas-dev.internal

# Certificates will be in /var/lib/data/traefik/certs/
```

### Install CA Certificate (for browser trust)

```bash
# On the server (RHEL/Rocky):
sudo cp /var/lib/data/traefik/certs/ca.crt /etc/pki/ca-trust/source/anchors/atlas-ca.crt
sudo update-ca-trust

# On client machines, distribute ca.crt and install in browser/system
```

## Step 4: Configure Production Environment

```bash
cd /var/lib/data/Atlas

# Copy deployment files
cp deployment/docker-compose.prod.yml docker-compose.yml
cp deployment/traefik/traefik.yml /var/lib/data/traefik/
cp deployment/traefik/docker-compose.yml /var/lib/data/traefik/
cp deployment/traefik/dynamic/atlas.yml /var/lib/data/traefik/dynamic/

# Create .env file from example
cp .env.example .env

# Edit .env with production values
nano .env
```

### Required .env Variables

```bash
# Minimum required for production:
ATLAS_SECRET_KEY=<generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
ATLAS_API_TOKEN=<your-api-token>
ATLAS_UI_PASSWORD=<your-ui-password>

# MongoDB (container networking)
MONGODB_URI=mongodb://mongodb:27017

# External services (adjust as needed)
NETBOX_URL=https://netbox.internal
NETBOX_TOKEN=<your-netbox-token>
```

## Step 5: Configure Development Environment

```bash
cd /var/lib/data/Atlas-dev

# Copy deployment files
cp deployment/docker-compose.dev.yml docker-compose.yml

# Create .env (can copy from prod or use different values)
cp .env.example .env
nano .env
```

## Step 6: Start Traefik (Reverse Proxy)

```bash
cd /var/lib/data/traefik

# Start Traefik
podman-compose up -d

# Verify it's running
podman-compose ps
podman-compose logs -f
```

## Step 7: Start Production Atlas

```bash
cd /var/lib/data/Atlas

# Build the image (first time)
podman-compose build

# Start all services
podman-compose up -d

# Check logs
podman-compose logs -f atlas

# Verify health
curl -k https://localhost/health
```

## Step 8: Start Development Atlas

```bash
cd /var/lib/data/Atlas-dev

# Use the same image or build separately
podman-compose up -d

# Check logs
podman-compose logs -f atlas

# Verify health (dev port)
curl -k https://localhost:8443/health
```

## Step 9: Enable Systemd Auto-Start

```bash
# Copy systemd service files
sudo cp /var/lib/data/Atlas/deployment/systemd/*.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable and start services
sudo systemctl enable --now atlas-traefik
sudo systemctl enable --now atlas-prod
sudo systemctl enable --now atlas-dev

# Check status
sudo systemctl status atlas-prod
sudo systemctl status atlas-dev
```

## Step 10: Migrate Data from Kubernetes

If you have existing data in Kubernetes:

```bash
# On the Kubernetes cluster, export MongoDB:
kubectl exec -n atlas atlas-mongodb-0 -- mongodump --out /tmp/dump
kubectl cp atlas/atlas-mongodb-0:/tmp/dump ./mongodb-backup

# Copy to new server
scp -r mongodb-backup user@sa-mgmt-tools-prod2:/tmp/

# On the new server, import:
cd /var/lib/data/Atlas
podman-compose exec mongodb mongorestore /tmp/mongodb-backup
```

---

## Useful Commands

### View Logs
```bash
# Production
cd /var/lib/data/Atlas && podman-compose logs -f

# Development
cd /var/lib/data/Atlas-dev && podman-compose logs -f

# Traefik
cd /var/lib/data/traefik && podman-compose logs -f
```

### Restart Services
```bash
# Via podman-compose
cd /var/lib/data/Atlas && podman-compose restart

# Via systemd
sudo systemctl restart atlas-prod
```

### Update Application
```bash
cd /var/lib/data/Atlas
git pull
podman-compose build
podman-compose up -d
```

### Backup MongoDB
```bash
/var/lib/data/scripts/backup-mongodb.sh prod
/var/lib/data/scripts/backup-mongodb.sh dev
```

---

## Ports Reference

| Service | Port | Protocol | Description |
|---------|------|----------|-------------|
| Traefik | 443 | HTTPS | Production Atlas |
| Traefik | 8443 | HTTPS | Development Atlas |
| Traefik | 8080 | HTTP | Traefik dashboard (localhost only) |
| MongoDB Prod | 27017 | TCP | Production database (internal) |
| MongoDB Dev | 27018 | TCP | Development database (internal) |

---

## Troubleshooting

### Permission Denied on Volumes
```bash
# SELinux fix (RHEL/Rocky):
sudo chcon -Rt svirt_sandbox_file_t /var/lib/data/

# Or add :Z to volume mounts in docker-compose.yml
```

### Container Won't Start
```bash
# Check logs
podman-compose logs atlas

# Check if ports are in use
sudo ss -tlnp | grep -E '443|8443|27017'
```

### Certificate Issues
```bash
# Regenerate certificates
cd /var/lib/data/scripts
./generate-certs.sh atlas.internal atlas-dev.internal

# Restart Traefik
cd /var/lib/data/traefik && podman-compose restart
```

---

## Server-Specific Configuration

### DNS Configuration for Containers

Containers need DNS servers that are allowed by the host firewall. Check which DNS servers are allowed:

```bash
# Check host DNS servers
resolvectl status | grep "DNS Servers"

# Check which DNS servers are allowed in firewall (iptables OUTPUT chain)
sudo iptables -L OUTPUT -n | grep "dpt:53"
```

Update `docker-compose.yml` to use the allowed DNS servers:

```yaml
services:
  atlas:
    dns:
      - 172.18.37.25  # Use your allowed internal DNS
      - 172.18.37.26
```

### Firewall Configuration (packetfilter/iptables)

If the server uses a custom firewall like `packetfilter`, add rules for Atlas:

**Inbound rules** (`/etc/packetfilter.conf.d/40.services/atlas.conf`):
```
# Atlas Infrastructure Platform - Inbound Rules
# raddr			|rp	|laddr			|lp	|pro |i	|dev |a|

# Allow HTTPS to Atlas Development (port 8443) from internal networks
172.18.0.0/16           |       |                       |8443   |tcp |R |    | |
10.0.0.0/8              |       |                       |8443   |tcp |R |    | |
```

**Outbound rules** (`/etc/packetfilter.conf.d/40.services/atlas-outbound.conf`):
```
# Atlas Infrastructure Platform - Outbound Rules
# raddr			|rp	|laddr			|lp	|pro |i	|dev |a|

# GitLab SSH access (for git operations)
                        |22     |                       |       |tcp |L |    | |
```

Reload firewall after changes:
```bash
sudo /usr/sbin/packetfilter reload
```

### Rootless Podman Networking Issues

Rootless Podman uses `slirp4netns` or `pasta` for networking. If containers can't reach external services:

**1. Check which network backend is in use:**
```bash
ps aux | grep -E "pasta|slirp" | grep -v grep
```

**2. Test container connectivity:**
```bash
podman exec atlas-prod curl -sk --connect-timeout 10 https://netbox.example.com/ -o /dev/null -w "%{http_code}\n"
```

**3. If DNS resolution fails, reload the network:**
```bash
# Kill aardvark-dns and reload network
pkill -u $(whoami) aardvark-dns
podman network reload atlas-prod
```

**4. If slirp4netns has issues, switch to pasta:**
```bash
# Create config
mkdir -p ~/.config/containers
cat > ~/.config/containers/containers.conf << 'EOF'
[network]
default_rootless_network_cmd = "pasta"
EOF

# Recreate containers
cd /var/lib/data/Atlas && podman-compose down && podman-compose up -d
```

### Verifying Outbound Connectivity

Test connectivity from containers to required services:

```bash
# Test from inside container
for srv in netbox.example.com zabbix.example.com vcenter.example.com; do
  podman exec atlas-prod curl -sk --connect-timeout 5 "https://${srv}/" \
    -o /dev/null -w "${srv}: %{http_code}\n"
done
```

Required outbound destinations for Atlas:
| Service | Port | Protocol |
|---------|------|----------|
| vCenter servers | 443 | HTTPS |
| NetBox | 443 | HTTPS |
| Zabbix | 443 | HTTPS |
| Commvault | 443 | HTTPS |
| Foreman | 443 | HTTPS |
| Atlassian | 443 | HTTPS |
| GitLab | 22 | SSH |
| AI APIs (OpenAI, etc.) | 443 | HTTPS |

---

## Settings Persistence

Admin UI settings are stored encrypted in MongoDB. For settings to persist across container restarts:

1. **Ensure `.env` file has real values** (not placeholders):
   ```bash
   # Check for placeholder values
   grep -E "example\.com|your-domain|placeholder" /var/lib/data/Atlas/.env
   ```

2. **Settings are synced to MongoDB** when saved via the admin UI. The sync uses the `SECURE_ENV_KEYS` list in `secret_store.py`.

3. **After updating `.env`, recreate containers** (restart is not enough):
   ```bash
   cd /var/lib/data/Atlas && podman-compose down && podman-compose up -d
   ```

---

## MongoDB Data Migration

### Copy data between instances (prod to dev):

```bash
# Direct pipeline - no intermediate files
podman exec atlas-mongodb-prod mongodump --archive --db=atlas | \
  podman exec -i atlas-mongodb-dev mongorestore --archive --drop
```

### Import from external MongoDB:

```bash
# Export from source
mongodump --uri="mongodb://source:27017" --archive > backup.archive

# Copy to server
scp backup.archive user@sa-mgmt-tools-prod2:/tmp/

# Import to container
podman exec -i atlas-mongodb-prod mongorestore --archive --drop < /tmp/backup.archive
```
