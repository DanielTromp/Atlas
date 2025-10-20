# Deployment Guide

## Overview

This document describes the automated deployment process for Infrastructure Atlas to production.

## Prerequisites

1. **SSH Access**: You must have SSH access to the production server
2. **rsync**: Required for file synchronization
3. **Production Configuration**: Set environment variables for production details

## Environment Variables

Configure these variables before deploying:

```bash
export PRODUCTION_HOST="production.example.com"   # Production server hostname
export PRODUCTION_PATH="/app/infrastructure-atlas"       # Installation path on server
export PRODUCTION_USER="atlas"                  # SSH user
```

You can also create a `.env.production` file:

```bash
# .env.production
PRODUCTION_HOST=production.example.com
PRODUCTION_PATH=/app/infrastructure-atlas
PRODUCTION_USER=atlas
```

Then source it before deploying:

```bash
source .env.production
./scripts/deploy_to_production.sh
```

## Deployment Process

### Automated Deployment

The automated deployment script handles the entire process:

```bash
./scripts/deploy_to_production.sh
```

### Dry Run

To preview changes without making modifications:

```bash
./scripts/deploy_to_production.sh --dry-run
```

### Skip Tests

If tests have already been run and you want to skip them:

```bash
./scripts/deploy_to_production.sh --skip-tests
```

## Deployment Steps

The script performs the following steps automatically:

### 1. Pre-deployment Checks
- Verifies git working directory is clean
- Checks current branch (warns if not on `main`)
- Ensures no uncommitted changes

### 2. Run Tests
- Executes full test suite: `uv run pytest`
- Fails deployment if any tests fail
- Can be skipped with `--skip-tests`

### 3. Check Migrations
- Verifies database migrations are up to date
- Runs: `uv run alembic check`

### 4. Create Backup
- Creates timestamped backup in `./backups/`
- Includes:
  - `data/atlas.db` (SQLite database)
  - `.env` file (environment configuration)
- Backup file: `backup_YYYYMMDD_HHMMSS.tar.gz`

### 5. Sync Code
- Uses `rsync` to sync code to production server
- Excludes:
  - `data/` directory (preserves production data)
  - `.git/` directory
  - `.venv/` directory
  - `__pycache__/` and `*.pyc` files
  - `.pytest_cache/`
  - `backups/`
  - `.env.local`
- Deletes files on production that don't exist locally

### 6. Run Migrations
- Executes migrations on production: `uv run alembic upgrade head`
- Fails deployment if migrations fail
- Preserves production database

### 7. Restart Services
- Restarts the API service: `sudo systemctl restart atlas-api`
- Requires sudo access configured on production server

### 8. Health Check
- Waits 3 seconds for service to start
- Checks: `https://{PRODUCTION_HOST}/api/health`
- Expects HTTP 200 response
- Fails deployment if health check fails

### 9. Deployment Complete
- Displays deployed commit hash
- Shows backup file location
- Provides rollback instructions

## Rollback Process

If deployment fails or issues are discovered:

### Manual Rollback

1. **Restore Database Backup**:
   ```bash
   # On production server
   cd /app/infrastructure-atlas
   tar -xzf /path/to/backup_YYYYMMDD_HHMMSS.tar.gz
   ```

2. **Restore Code** (if needed):
   ```bash
   # On development machine
   git checkout <previous-commit-hash>
   ./scripts/deploy_to_production.sh
   ```

3. **Restart Services**:
   ```bash
   # On production server
   sudo systemctl restart atlas-api
   ```

### Automatic Rollback (Future Enhancement)

A rollback script can be added:

```bash
./scripts/rollback_production.sh backup_YYYYMMDD_HHMMSS.tar.gz
```

## Production Server Setup

### Initial Setup

1. **Install Dependencies**:
   ```bash
   # On production server
   sudo apt-get update
   sudo apt-get install -y python3 python3-pip sqlite3
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Create Directory**:
   ```bash
   sudo mkdir -p /app/infrastructure-atlas
   sudo chown atlas:atlas /app/infrastructure-atlas
   ```

3. **Clone Repository**:
   ```bash
   cd /app/infrastructure-atlas
   git clone <repository-url> .
   ```

4. **Install Python Dependencies**:
   ```bash
   uv venv
   uv pip install -e .
   ```

5. **Configure Environment**:
   ```bash
   cp .env.example .env
   # Edit .env with production values
   ```

6. **Run Initial Migrations**:
   ```bash
   uv run alembic upgrade head
   ```

### Systemd Service

Create `/etc/systemd/system/atlas-api.service`:

```ini
[Unit]
Description=Infrastructure Atlas API
After=network.target

[Service]
Type=simple
User=atlas
Group=atlas
WorkingDirectory=/app/infrastructure-atlas
Environment="PATH=/home/atlas/.local/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/home/atlas/.local/bin/uv run atlas api serve --host 0.0.0.0 --port 8443
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable atlas-api
sudo systemctl start atlas-api
```

### Sudo Configuration

Allow atlas user to restart services without password:

```bash
# /etc/sudoers.d/atlas
atlas ALL=(ALL) NOPASSWD: /bin/systemctl restart atlas-api
```

## Monitoring Deployment

### View Service Logs

```bash
# On production server
sudo journalctl -u atlas-api -f
```

### Check Service Status

```bash
sudo systemctl status atlas-api
```

### Database Verification

```bash
# On production server
cd /app/infrastructure-atlas
sqlite3 data/atlas.db "SELECT name FROM sqlite_master WHERE type='table';"
```

## Troubleshooting

### Deployment Fails at Migration Step

**Symptom**: Migration fails on production

**Solution**:
1. SSH to production server
2. Check migration status: `uv run alembic current`
3. Review migration logs
4. Manually fix migration issues
5. Re-run deployment

### Health Check Fails

**Symptom**: HTTP health check returns non-200 status

**Solution**:
1. Check service logs: `sudo journalctl -u atlas-api -n 50`
2. Verify service is running: `sudo systemctl status atlas-api`
3. Check port binding: `sudo lsof -i :8443`
4. Review .env configuration
5. Restart service: `sudo systemctl restart atlas-api`

### rsync Permission Denied

**Symptom**: Cannot sync files to production

**Solution**:
1. Verify SSH access: `ssh atlas@production`
2. Check directory permissions on production
3. Ensure atlas user owns `/app/infrastructure-atlas`

### Git Working Directory Not Clean

**Symptom**: Deployment fails due to uncommitted changes

**Solution**:
```bash
git status
git add .
git commit -m "Deploy changes"
./scripts/deploy_to_production.sh
```

## Best Practices

1. **Always Test First**: Run full test suite before deploying
2. **Deploy from main**: Keep main branch stable and deploy from it
3. **Review Changes**: Check `git log` to see what's being deployed
4. **Monitor After Deploy**: Watch logs for 5-10 minutes after deployment
5. **Keep Backups**: Backups are automatic but verify they're created
6. **Off-Peak Deployments**: Deploy during low-traffic periods if possible
7. **Incremental Changes**: Deploy small, incremental changes rather than large batches

## Future Enhancements

- [ ] Blue-green deployment strategy
- [ ] Automatic rollback on failed health check
- [ ] Deployment notifications (Slack, email)
- [ ] Database migration dry-run preview
- [ ] Integration with CI/CD pipeline
- [ ] Deployment metrics and monitoring
- [ ] Canary deployments for gradual rollout
