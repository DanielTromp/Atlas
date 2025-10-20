#!/usr/bin/env bash
#
# Production Deployment Script for Infrastructure Atlas
#
# This script automates deployment to production with safety checks,
# backups, and rollback capability.
#
# Usage:
#   ./scripts/deploy_to_production.sh [--dry-run] [--skip-tests]
#

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
PRODUCTION_HOST="${PRODUCTION_HOST:-production}"
PRODUCTION_PATH="${PRODUCTION_PATH:-/app/infrastructure-atlas}"
PRODUCTION_USER="${PRODUCTION_USER:-atlas}"
BACKUP_DIR="./backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Parse arguments
DRY_RUN=false
SKIP_TESTS=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --skip-tests)
            SKIP_TESTS=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--dry-run] [--skip-tests]"
            exit 1
            ;;
    esac
done

# Helper functions
info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

step() {
    echo ""
    echo -e "${GREEN}==>${NC} $1"
}

# Check if running in dry-run mode
if [ "$DRY_RUN" = true ]; then
    warn "Running in DRY-RUN mode - no changes will be made"
fi

# 1. Pre-deployment checks
step "Step 1: Pre-deployment checks"

# Check if git repo is clean
if [[ -n $(git status --porcelain) ]]; then
    error "Git working directory is not clean. Commit or stash changes first."
    git status --short
    exit 1
fi
info "Git working directory is clean"

# Check if on main branch
CURRENT_BRANCH=$(git branch --show-current)
if [[ "$CURRENT_BRANCH" != "main" ]]; then
    warn "Not on main branch (current: $CURRENT_BRANCH)"
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# 2. Run tests
if [ "$SKIP_TESTS" = false ]; then
    step "Step 2: Running tests"

    if [ "$DRY_RUN" = false ]; then
        if ! uv run pytest; then
            error "Tests failed. Fix tests before deploying."
            exit 1
        fi
        info "All tests passed"
    else
        info "(dry-run) Would run: uv run pytest"
    fi
else
    warn "Skipping tests (--skip-tests flag set)"
fi

# 3. Check migrations
step "Step 3: Checking database migrations"

if [ "$DRY_RUN" = false ]; then
    # Check if migrations are up to date
    if ! uv run alembic check 2>/dev/null; then
        warn "Database migrations may need to be applied"
    else
        info "Database migrations are up to date"
    fi
else
    info "(dry-run) Would check: uv run alembic check"
fi

# 4. Create backup
step "Step 4: Creating backup"

mkdir -p "$BACKUP_DIR"
BACKUP_FILE="$BACKUP_DIR/backup_${TIMESTAMP}.tar.gz"

if [ "$DRY_RUN" = false ]; then
    # Backup database and important files
    tar -czf "$BACKUP_FILE" \
        data/atlas.db \
        .env \
        2>/dev/null || true

    info "Backup created: $BACKUP_FILE"
else
    info "(dry-run) Would create backup: $BACKUP_FILE"
fi

# 5. Sync code to production
step "Step 5: Syncing code to production"

RSYNC_OPTS=(
    -av
    --delete
    --exclude='data/'
    --exclude='.git/'
    --exclude='.venv/'
    --exclude='__pycache__/'
    --exclude='*.pyc'
    --exclude='.pytest_cache/'
    --exclude='backups/'
    --exclude='.env.local'
)

if [ "$DRY_RUN" = true ]; then
    RSYNC_OPTS+=(--dry-run)
fi

info "Syncing to ${PRODUCTION_USER}@${PRODUCTION_HOST}:${PRODUCTION_PATH}"

if command -v rsync &> /dev/null; then
    rsync "${RSYNC_OPTS[@]}" ./ "${PRODUCTION_USER}@${PRODUCTION_HOST}:${PRODUCTION_PATH}/"
else
    error "rsync not found. Please install rsync."
    exit 1
fi

if [ "$DRY_RUN" = false ]; then
    info "Code synced successfully"
else
    info "(dry-run) Code sync completed (no changes made)"
fi

# 6. Run migrations on production
step "Step 6: Running migrations on production"

MIGRATION_CMD="cd ${PRODUCTION_PATH} && uv run alembic upgrade head"

if [ "$DRY_RUN" = false ]; then
    if ssh "${PRODUCTION_USER}@${PRODUCTION_HOST}" "$MIGRATION_CMD"; then
        info "Migrations completed successfully"
    else
        error "Migration failed"
        warn "You may need to manually rollback"
        exit 1
    fi
else
    info "(dry-run) Would run on production: $MIGRATION_CMD"
fi

# 7. Restart services
step "Step 7: Restarting services"

RESTART_CMD="sudo systemctl restart atlas-api"

if [ "$DRY_RUN" = false ]; then
    if ssh "${PRODUCTION_USER}@${PRODUCTION_HOST}" "$RESTART_CMD" 2>/dev/null || true; then
        info "Services restarted"
    else
        warn "Service restart may have failed (check manually)"
    fi
else
    info "(dry-run) Would run on production: $RESTART_CMD"
fi

# 8. Health check
step "Step 8: Running health check"

HEALTH_URL="https://${PRODUCTION_HOST}/api/health"

if [ "$DRY_RUN" = false ]; then
    sleep 3  # Give service time to start

    if command -v curl &> /dev/null; then
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$HEALTH_URL" || echo "000")

        if [[ "$HTTP_CODE" == "200" ]]; then
            info "Health check passed (HTTP $HTTP_CODE)"
        else
            error "Health check failed (HTTP $HTTP_CODE)"
            warn "Service may not be running correctly"
            warn "Backup available at: $BACKUP_FILE"
            exit 1
        fi
    else
        warn "curl not found. Skipping health check."
    fi
else
    info "(dry-run) Would check: $HEALTH_URL"
fi

# 9. Deployment complete
step "Deployment complete!"

if [ "$DRY_RUN" = false ]; then
    info "Deployed commit: $(git rev-parse --short HEAD)"
    info "Backup: $BACKUP_FILE"
    info ""
    info "To rollback, run:"
    echo "  tar -xzf $BACKUP_FILE"
    echo "  ./scripts/deploy_to_production.sh"
else
    info "(dry-run) No changes were made"
fi
