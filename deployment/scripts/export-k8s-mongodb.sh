#!/bin/bash
# Export MongoDB data from Kubernetes for migration
# Usage: ./export-k8s-mongodb.sh [namespace] [pod-name]
#
# This script exports MongoDB data from a Kubernetes cluster
# and prepares it for import on the new Podman-based deployment.
#
# Run this on a machine with kubectl access to the cluster.

set -e

# Configuration
NAMESPACE="${1:-atlas}"
MONGODB_POD="${2:-atlas-mongodb-0}"
BACKUP_DIR="${3:-./mongodb-export}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="atlas-mongodb-$TIMESTAMP.archive"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║       Atlas MongoDB Export from Kubernetes                 ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}Configuration:${NC}"
echo "  Namespace:    $NAMESPACE"
echo "  Pod:          $MONGODB_POD"
echo "  Backup dir:   $BACKUP_DIR"
echo "  Output file:  $BACKUP_FILE"
echo ""

# Check kubectl is available
if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}Error: kubectl not found${NC}"
    exit 1
fi

# Check we can reach the cluster
echo -e "${YELLOW}Checking cluster connectivity...${NC}"
if ! kubectl cluster-info &> /dev/null; then
    echo -e "${RED}Error: Cannot connect to Kubernetes cluster${NC}"
    echo "Make sure kubectl is configured correctly"
    exit 1
fi
echo -e "${GREEN}✓ Connected to cluster${NC}"

# Check the pod exists
echo -e "${YELLOW}Checking MongoDB pod...${NC}"
if ! kubectl get pod -n "$NAMESPACE" "$MONGODB_POD" &> /dev/null; then
    echo -e "${RED}Error: Pod $MONGODB_POD not found in namespace $NAMESPACE${NC}"
    echo ""
    echo "Available pods:"
    kubectl get pods -n "$NAMESPACE" 2>/dev/null || echo "  (namespace not found)"
    exit 1
fi
echo -e "${GREEN}✓ Pod found${NC}"

# Check MongoDB is running
echo -e "${YELLOW}Checking MongoDB status...${NC}"
if ! kubectl exec -n "$NAMESPACE" "$MONGODB_POD" -- mongosh --eval "db.adminCommand('ping')" &> /dev/null; then
    echo -e "${RED}Error: MongoDB is not responding${NC}"
    exit 1
fi
echo -e "${GREEN}✓ MongoDB is healthy${NC}"

# Show database stats
echo ""
echo -e "${BLUE}Database statistics:${NC}"
kubectl exec -n "$NAMESPACE" "$MONGODB_POD" -- mongosh --quiet --eval "
    const dbs = db.adminCommand('listDatabases');
    print('Databases:');
    dbs.databases.forEach(d => {
        print('  - ' + d.name + ': ' + (d.sizeOnDisk / 1024 / 1024).toFixed(2) + ' MB');
    });
    print('Total size: ' + (dbs.totalSize / 1024 / 1024).toFixed(2) + ' MB');
"

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Export using mongodump with archive format (single file, compressed)
echo ""
echo -e "${YELLOW}Exporting MongoDB data...${NC}"
echo "This may take a few minutes depending on database size."
echo ""

kubectl exec -n "$NAMESPACE" "$MONGODB_POD" -- mongodump \
    --archive \
    --gzip \
    --db atlas \
    > "$BACKUP_DIR/$BACKUP_FILE"

# Check backup was created
if [ ! -f "$BACKUP_DIR/$BACKUP_FILE" ]; then
    echo -e "${RED}Error: Backup file was not created${NC}"
    exit 1
fi

BACKUP_SIZE=$(ls -lh "$BACKUP_DIR/$BACKUP_FILE" | awk '{print $5}')
echo -e "${GREEN}✓ Export complete${NC}"

# Also export secure_settings separately (important for encrypted credentials)
echo ""
echo -e "${YELLOW}Exporting secure_settings collection...${NC}"
kubectl exec -n "$NAMESPACE" "$MONGODB_POD" -- mongodump \
    --archive \
    --gzip \
    --db atlas \
    --collection secure_settings \
    > "$BACKUP_DIR/secure_settings-$TIMESTAMP.archive" 2>/dev/null || true

# Create a metadata file
cat > "$BACKUP_DIR/export-metadata.json" << EOF
{
    "export_timestamp": "$TIMESTAMP",
    "source": {
        "type": "kubernetes",
        "namespace": "$NAMESPACE",
        "pod": "$MONGODB_POD"
    },
    "files": {
        "full_backup": "$BACKUP_FILE",
        "secure_settings": "secure_settings-$TIMESTAMP.archive"
    },
    "notes": [
        "Use mongorestore --archive --gzip < file.archive to restore",
        "Secure settings require ATLAS_SECRET_KEY to decrypt",
        "Import secure_settings first if restoring to new database"
    ]
}
EOF

echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                    Export Complete                         ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}Files created in $BACKUP_DIR/:${NC}"
ls -lh "$BACKUP_DIR/"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo ""
echo "1. Copy files to the new server:"
echo -e "   ${BLUE}scp -r $BACKUP_DIR user@sa-mgmt-tools-prod2:/tmp/${NC}"
echo ""
echo "2. On the new server, restore to production MongoDB:"
echo -e "   ${BLUE}podman exec -i atlas-mongodb-prod mongorestore --archive --gzip < /tmp/mongodb-export/$BACKUP_FILE${NC}"
echo ""
echo "3. Verify the restore:"
echo -e "   ${BLUE}podman exec atlas-mongodb-prod mongosh atlas --eval \"db.getCollectionNames()\"${NC}"
echo ""
echo -e "${YELLOW}Important:${NC}"
echo "- Make sure ATLAS_SECRET_KEY on the new server matches the original"
echo "- Otherwise encrypted settings (API tokens, passwords) won't decrypt"
echo ""
