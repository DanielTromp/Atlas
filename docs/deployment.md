# Container Deployment Guide

This guide covers deploying Infrastructure Atlas using Docker or Podman containers.

## Quick Start

```bash
# 1. Configure environment
cp .env.example .env
# Edit .env with your credentials

# 2. Start the stack
docker compose up -d

# 3. Access the web UI
open http://localhost:8000/app/
```

## Architecture

The containerized deployment includes:

| Service | Port | Description |
|---------|------|-------------|
| `atlas` | 8000 | API server and web UI |
| `mongodb` | 27017 | Primary database |
| `qdrant` | 6333/6334 | Vector DB for RAG (optional) |
| `slack-bot` | - | Slack bot (optional) |
| `telegram-bot` | - | Telegram bot (optional) |

## Installation

### Prerequisites

- Docker 24+ or Podman 4+
- Docker Compose v2 or podman-compose
- 2GB+ RAM (4GB+ recommended with RAG)
- `.env` file configured

### Build the Image

```bash
# Docker
docker build -t atlas:latest .

# Podman
podman build -t atlas:latest .
```

### Start Services

```bash
# Core services (Atlas + MongoDB)
docker compose up -d

# With Confluence RAG (adds Qdrant)
docker compose --profile rag up -d

# With chat bots (Slack/Telegram)
docker compose --profile bots up -d

# Full stack (all services)
docker compose --profile full up -d
```

## Common Operations

### View Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f atlas

# Last 100 lines
docker compose logs --tail=100 atlas
```

### Check Status

```bash
# Service status
docker compose ps

# Health check
curl http://localhost:8000/api/health

# Detailed health
docker inspect atlas-server --format='{{.State.Health.Status}}'
```

### Stop Services

```bash
# Stop all
docker compose down

# Stop specific service
docker compose stop atlas

# Stop and remove volumes (WARNING: deletes data)
docker compose down -v
```

### Restart Services

```bash
# Restart all
docker compose restart

# Restart specific service
docker compose restart atlas

# Recreate containers (after config change)
docker compose up -d --force-recreate
```

## Updating

### Update to Latest Code

```bash
# Pull latest code
git pull

# Rebuild image
docker compose build

# Restart with new image
docker compose up -d
```

### Update with Zero Downtime

```bash
# Build new image
docker compose build atlas

# Scale up new instance
docker compose up -d --no-deps --scale atlas=2 atlas

# Wait for health check
sleep 30

# Remove old instance
docker compose up -d --no-deps --scale atlas=1 atlas
```

## Configuration

### Environment Variables

Create `.env` from the template:

```bash
cp .env.example .env
```

Key variables for container deployment:

```bash
# Database (auto-configured in docker-compose)
MONGODB_URI=mongodb://mongodb:27017

# Session secret - REQUIRED for multi-worker deployments
# Generate with: python -c "import secrets; print(secrets.token_hex(32))"
ATLAS_UI_SECRET=your-64-char-hex-secret

# API Authentication
ATLAS_API_TOKEN=your-secure-token
ATLAS_UI_PASSWORD=your-secure-password

# Admin bootstrap
ATLAS_DEFAULT_ADMIN_USERNAME=admin
ATLAS_DEFAULT_ADMIN_PASSWORD=your-admin-password

# Performance (set in Dockerfile, can override)
ATLAS_SKIP_DB_HEALTH_CHECK=1
ATLAS_LAZY_AI_IMPORTS=1
```

**Important:** `ATLAS_UI_SECRET` must be set for multi-worker deployments. Without it, each worker generates a random session secret, causing sessions to break when requests hit different workers.

### Custom Port

```bash
# Change exposed port
docker compose run -d -p 9000:8000 atlas
```

Or modify `docker-compose.yml`:

```yaml
services:
  atlas:
    ports:
      - "9000:8000"
```

### HTTPS with Reverse Proxy

For production, use a reverse proxy (nginx, Traefik, Caddy):

```yaml
# docker-compose.override.yml
services:
  traefik:
    image: traefik:v3.0
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./traefik:/etc/traefik

  atlas:
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.atlas.rule=Host(`atlas.example.com`)"
      - "traefik.http.routers.atlas.tls.certresolver=letsencrypt"
```

### Persistent Data

Data is stored in Docker volumes:

| Volume | Purpose |
|--------|---------|
| `atlas_data` | Cache files, exports |
| `atlas_logs` | Application logs |
| `mongodb_data` | Database files |
| `qdrant_storage` | Vector embeddings |

To backup:

```bash
# Backup MongoDB
docker exec atlas-mongodb mongodump --out=/backup
docker cp atlas-mongodb:/backup ./backup-$(date +%Y%m%d)

# Backup volumes
docker run --rm -v atlas_data:/data -v $(pwd):/backup alpine \
  tar czf /backup/atlas_data.tar.gz /data
```

## Podman-Specific Instructions

Podman is fully compatible with this setup. Key differences:

### Using podman-compose

```bash
# Install podman-compose
pip install podman-compose

# Use same commands
podman-compose up -d
podman-compose logs -f atlas
podman-compose down
```

### Using pods

```bash
# Create pod
podman pod create --name atlas-pod -p 8000:8000 -p 27017:27017

# Run MongoDB in pod
podman run -d --pod atlas-pod --name mongodb mongo:7.0

# Run Atlas in pod
podman run -d --pod atlas-pod --name atlas \
  --env-file .env \
  -e MONGODB_URI=mongodb://localhost:27017 \
  atlas:latest
```

### Rootless Podman

The Dockerfile is designed to work rootless:

```bash
# Build as non-root
podman build -t atlas:latest .

# Run as non-root (default)
podman run -d -p 8000:8000 --env-file .env atlas:latest
```

### Systemd Integration

Generate and install systemd service:

```bash
# Generate service file
podman generate systemd --new --name atlas-server > ~/.config/systemd/user/atlas.service

# Enable and start
systemctl --user daemon-reload
systemctl --user enable --now atlas.service

# Check status
systemctl --user status atlas.service
```

## Scaling

### Multiple Workers

The default CMD runs 4 uvicorn workers. Adjust in docker-compose:

```yaml
services:
  atlas:
    command: ["uvicorn", "infrastructure_atlas.api.app:app",
              "--host", "0.0.0.0", "--port", "8000", "--workers", "8"]
```

### Multiple Containers

For high availability:

```yaml
services:
  atlas:
    deploy:
      replicas: 3
    # Remove container_name for multiple replicas
```

With load balancer:

```bash
docker compose up -d --scale atlas=3
```

## Troubleshooting

### Container Won't Start

```bash
# Check logs
docker compose logs atlas

# Common issues:
# - Missing .env file
# - MongoDB not ready (increase start_period)
# - Port already in use
```

### MongoDB Connection Failed

```bash
# Check MongoDB is running
docker compose ps mongodb

# Test connection
docker exec atlas-mongodb mongosh --eval "db.adminCommand('ping')"

# Check network
docker network inspect atlas_default
```

### Slow Startup

Ensure optimization env vars are set:

```bash
ATLAS_SKIP_DB_HEALTH_CHECK=1
ATLAS_LAZY_AI_IMPORTS=1
```

### Out of Memory

Increase container memory limits:

```yaml
services:
  atlas:
    deploy:
      resources:
        limits:
          memory: 4G
```

### Permission Denied

For Podman rootless or SELinux:

```bash
# Add :Z suffix for SELinux
volumes:
  - ./data:/app/data:Z

# Or disable SELinux for the container
podman run --security-opt label=disable ...
```

## Health Checks

The Atlas container includes a health check:

```bash
# Check health status
docker inspect atlas-server --format='{{json .State.Health}}'

# Manual health check
curl -f http://localhost:8000/api/health
```

Health check endpoint returns:
- `200 OK` - Service healthy
- `401 Unauthorized` - Service running (auth required)
- `5xx` - Service unhealthy

## Bot Deployment

The Slack and Telegram bots run as separate containers, allowing independent scaling and management.

### Starting Bots

```bash
# Start all bots
docker compose --profile bots up -d

# Start specific bot
docker compose --profile bots up -d slack-bot
docker compose --profile bots up -d telegram-bot

# View bot logs
docker compose logs -f slack-bot
docker compose logs -f telegram-bot
```

### Required Configuration

Add to your `.env` file:

```bash
# Enable bots module
ATLAS_MODULE_BOTS_ENABLED=1

# Slack Bot (Socket Mode - no public URL required)
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_APP_TOKEN=xapp-your-app-level-token

# Telegram Bot (Polling Mode - no public URL required)
TELEGRAM_BOT_TOKEN=your-bot-token-from-botfather
```

### Bot Container Features

| Feature | Description |
|---------|-------------|
| **Auto-restart** | `restart: unless-stopped` ensures uptime |
| **Log rotation** | 10MB max size, 3 files retained |
| **VPN DNS** | Internal DNS servers for VPN access |
| **MongoDB** | Shared database for conversations |
| **No build required** | Uses pre-built `atlas:latest` image |

### Slack Bot Setup

1. Create app at [api.slack.com/apps](https://api.slack.com/apps)
2. Enable Socket Mode
3. Generate App-Level Token with `connections:write` scope
4. Add Bot Token Scopes: `app_mentions:read`, `chat:write`, `files:write`, `im:history`, `im:read`, `im:write`, `users:read`
5. Subscribe to events: `message.im`, `app_mention`
6. Install to workspace

### Telegram Bot Setup

1. Message [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` and follow prompts
3. Copy the bot token to `.env`

### Account Linking

Users must link their platform accounts to Atlas:

```bash
# Generate verification code
docker compose exec atlas atlas bots link-user <username> slack

# User sends to bot
!link <code>   # Slack
/link <code>   # Telegram
```

See [Bot System Documentation](bots.md) for detailed setup and usage.

## Security Best Practices

1. **Never commit `.env`** - Use secrets management in production
2. **Use HTTPS** - Deploy behind a reverse proxy with TLS
3. **Limit network exposure** - Don't expose MongoDB port in production
4. **Run rootless** - Use Podman or Docker rootless mode
5. **Scan images** - Use `docker scan` or `trivy` before deployment
6. **Update regularly** - Rebuild images to get security patches

```bash
# Scan image for vulnerabilities
docker scout cves atlas:latest

# Or with trivy
trivy image atlas:latest
```
