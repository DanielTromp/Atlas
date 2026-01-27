#!/bin/bash
# Backup MongoDB for Atlas
# Usage: ./backup-mongodb.sh [prod|dev]
#
# Creates timestamped backups in /var/lib/data/backups/

set -e

ENV="${1:-prod}"
BACKUP_DIR="/var/lib/data/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

case "$ENV" in
    prod)
        COMPOSE_DIR="/var/lib/data/Atlas"
        CONTAINER="atlas-mongodb-prod"
        ;;
    dev)
        COMPOSE_DIR="/var/lib/data/Atlas-dev"
        CONTAINER="atlas-mongodb-dev"
        ;;
    *)
        echo "Usage: $0 [prod|dev]"
        exit 1
        ;;
esac

BACKUP_PATH="$BACKUP_DIR/mongodb-$ENV-$TIMESTAMP"

echo -e "${GREEN}=== MongoDB Backup ===${NC}"
echo "Environment: $ENV"
echo "Container: $CONTAINER"
echo "Backup path: $BACKUP_PATH"
echo ""

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Run mongodump inside the container
echo -e "${YELLOW}Running mongodump...${NC}"
podman exec "$CONTAINER" mongodump --out /tmp/backup

# Copy backup from container
echo -e "${YELLOW}Copying backup...${NC}"
podman cp "$CONTAINER:/tmp/backup" "$BACKUP_PATH"

# Cleanup inside container
podman exec "$CONTAINER" rm -rf /tmp/backup

# Compress backup
echo -e "${YELLOW}Compressing...${NC}"
tar -czf "$BACKUP_PATH.tar.gz" -C "$BACKUP_DIR" "mongodb-$ENV-$TIMESTAMP"
rm -rf "$BACKUP_PATH"

# Show result
echo ""
echo -e "${GREEN}Backup complete:${NC}"
ls -lh "$BACKUP_PATH.tar.gz"

# Cleanup old backups (keep last 7)
echo ""
echo -e "${YELLOW}Cleaning old backups (keeping last 7)...${NC}"
ls -t "$BACKUP_DIR"/mongodb-$ENV-*.tar.gz 2>/dev/null | tail -n +8 | xargs -r rm -f

echo ""
echo "Existing backups:"
ls -lh "$BACKUP_DIR"/mongodb-$ENV-*.tar.gz 2>/dev/null || echo "  (none)"
