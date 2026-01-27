#!/bin/bash
# Import MongoDB data on the new Podman-based deployment
# Usage: ./import-mongodb.sh <backup-file> [prod|dev]
#
# Run this on sa-mgmt-tools-prod2 after copying the export files.

set -e

BACKUP_FILE="${1}"
ENV="${2:-prod}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Validate arguments
if [ -z "$BACKUP_FILE" ]; then
    echo -e "${RED}Usage: $0 <backup-file.archive> [prod|dev]${NC}"
    echo ""
    echo "Examples:"
    echo "  $0 /tmp/mongodb-export/atlas-mongodb-20260127_120000.archive prod"
    echo "  $0 /tmp/mongodb-export/atlas-mongodb-20260127_120000.archive dev"
    exit 1
fi

if [ ! -f "$BACKUP_FILE" ]; then
    echo -e "${RED}Error: Backup file not found: $BACKUP_FILE${NC}"
    exit 1
fi

case "$ENV" in
    prod)
        CONTAINER="atlas-mongodb-prod"
        COMPOSE_DIR="/var/lib/data/Atlas"
        ;;
    dev)
        CONTAINER="atlas-mongodb-dev"
        COMPOSE_DIR="/var/lib/data/Atlas-dev"
        ;;
    *)
        echo -e "${RED}Error: Environment must be 'prod' or 'dev'${NC}"
        exit 1
        ;;
esac

echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║           Atlas MongoDB Import                             ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}Configuration:${NC}"
echo "  Backup file:  $BACKUP_FILE"
echo "  Environment:  $ENV"
echo "  Container:    $CONTAINER"
echo ""

# Check container is running
echo -e "${YELLOW}Checking MongoDB container...${NC}"
if ! podman ps --format "{{.Names}}" | grep -q "^${CONTAINER}$"; then
    echo -e "${RED}Error: Container $CONTAINER is not running${NC}"
    echo ""
    echo "Start the services first:"
    echo "  cd $COMPOSE_DIR && podman-compose up -d"
    exit 1
fi
echo -e "${GREEN}✓ Container is running${NC}"

# Check MongoDB is healthy
echo -e "${YELLOW}Checking MongoDB health...${NC}"
if ! podman exec "$CONTAINER" mongosh --quiet --eval "db.adminCommand('ping')" &> /dev/null; then
    echo -e "${RED}Error: MongoDB is not responding${NC}"
    exit 1
fi
echo -e "${GREEN}✓ MongoDB is healthy${NC}"

# Show current database state
echo ""
echo -e "${BLUE}Current database state:${NC}"
podman exec "$CONTAINER" mongosh --quiet --eval "
    const dbs = db.adminCommand('listDatabases');
    if (dbs.databases.length === 0) {
        print('  (empty - no databases)');
    } else {
        dbs.databases.forEach(d => {
            print('  - ' + d.name + ': ' + (d.sizeOnDisk / 1024 / 1024).toFixed(2) + ' MB');
        });
    }
"

# Confirm import
echo ""
echo -e "${YELLOW}WARNING: This will import data into the $ENV database.${NC}"
echo -e "${YELLOW}Existing data with the same _id values will be overwritten.${NC}"
echo ""
read -p "Continue with import? (y/N): " confirm
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "Import cancelled."
    exit 0
fi

# Perform import
echo ""
echo -e "${YELLOW}Importing data...${NC}"
echo "This may take a few minutes depending on backup size."
echo ""

# Check if file is gzipped
if file "$BACKUP_FILE" | grep -q "gzip"; then
    podman exec -i "$CONTAINER" mongorestore --archive --gzip < "$BACKUP_FILE"
else
    podman exec -i "$CONTAINER" mongorestore --archive < "$BACKUP_FILE"
fi

echo ""
echo -e "${GREEN}✓ Import complete${NC}"

# Show post-import state
echo ""
echo -e "${BLUE}Database state after import:${NC}"
podman exec "$CONTAINER" mongosh --quiet --eval "
    const dbs = db.adminCommand('listDatabases');
    dbs.databases.forEach(d => {
        print('  - ' + d.name + ': ' + (d.sizeOnDisk / 1024 / 1024).toFixed(2) + ' MB');
    });
"

# Show atlas database collections
echo ""
echo -e "${BLUE}Collections in 'atlas' database:${NC}"
podman exec "$CONTAINER" mongosh atlas --quiet --eval "
    db.getCollectionNames().forEach(c => {
        const count = db.getCollection(c).countDocuments();
        print('  - ' + c + ': ' + count + ' documents');
    });
"

echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                   Import Complete                          ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "1. Restart Atlas to pick up the imported data:"
echo -e "   ${BLUE}cd $COMPOSE_DIR && podman-compose restart atlas${NC}"
echo ""
echo "2. Verify the application is working:"
echo -e "   ${BLUE}curl -k https://localhost/health${NC}"
echo ""
echo -e "${YELLOW}Note:${NC}"
echo "- If encrypted settings don't work, verify ATLAS_SECRET_KEY matches the original"
echo "- Check logs for any decryption errors: podman logs $CONTAINER"
echo ""
