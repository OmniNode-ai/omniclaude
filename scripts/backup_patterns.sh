#!/bin/bash
################################################################################
# Pattern System Backup Script
################################################################################
# Purpose: Create full backup of pattern system before migration
# Usage: ./scripts/backup_patterns.sh
# Output: backup_patterns_YYYYMMDD_HHMMSS.sql
################################################################################

set -e  # Exit on error
set -u  # Exit on undefined variable

# Configuration
DB_HOST="${POSTGRES_HOST:-192.168.86.200}"
DB_PORT="${POSTGRES_PORT:-5436}"
DB_USER="${POSTGRES_USER:-postgres}"
DB_NAME="${POSTGRES_DATABASE:-omninode_bridge}"
DB_PASSWORD="${POSTGRES_PASSWORD}"  # Must be set in environment

# Verify password is set
if [ -z "$DB_PASSWORD" ]; then
    echo -e "${RED}❌ ERROR: POSTGRES_PASSWORD environment variable not set${NC}"
    echo "   Please run: source .env"
    exit 1
fi

# Generate timestamped backup filename
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="./backups"
BACKUP_FILE="${BACKUP_DIR}/backup_patterns_${TIMESTAMP}.sql"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo "=========================================="
echo "Pattern System Backup"
echo "=========================================="
echo ""

# Create backup directory if it doesn't exist
if [ ! -d "$BACKUP_DIR" ]; then
    echo -e "${YELLOW}Creating backup directory: $BACKUP_DIR${NC}"
    mkdir -p "$BACKUP_DIR"
fi

# Pre-backup statistics
echo -e "${YELLOW}Collecting pre-backup statistics...${NC}"
PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c "
SELECT
  'pattern_lineage_nodes: ' || COUNT(*)
FROM pattern_lineage_nodes
UNION ALL
SELECT
  'pattern_lineage_edges: ' || COUNT(*)
FROM pattern_lineage_edges
UNION ALL
SELECT
  'pattern_relationships: ' || COUNT(*)
FROM pattern_relationships;
"

echo ""
echo -e "${YELLOW}Creating backup: $BACKUP_FILE${NC}"

# Create backup
PGPASSWORD="$DB_PASSWORD" pg_dump \
  -h "$DB_HOST" \
  -p "$DB_PORT" \
  -U "$DB_USER" \
  -d "$DB_NAME" \
  --table pattern_lineage_nodes \
  --table pattern_lineage_edges \
  --table pattern_relationships \
  --no-owner \
  --no-acl \
  --format=plain \
  --file="$BACKUP_FILE"

# Verify backup
if [ -f "$BACKUP_FILE" ]; then
    BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    echo -e "${GREEN}✓ Backup created successfully${NC}"
    echo "  File: $BACKUP_FILE"
    echo "  Size: $BACKUP_SIZE"

    # Count lines in backup
    LINE_COUNT=$(wc -l < "$BACKUP_FILE")
    echo "  Lines: $LINE_COUNT"

    # Create checksum
    if command -v md5 &> /dev/null; then
        CHECKSUM=$(md5 -q "$BACKUP_FILE")
        echo "  MD5: $CHECKSUM"
        echo "$CHECKSUM  $BACKUP_FILE" > "${BACKUP_FILE}.md5"
    elif command -v md5sum &> /dev/null; then
        CHECKSUM=$(md5sum "$BACKUP_FILE" | cut -d' ' -f1)
        echo "  MD5: $CHECKSUM"
        echo "$CHECKSUM  $BACKUP_FILE" > "${BACKUP_FILE}.md5"
    fi
else
    echo -e "${RED}✗ Backup failed!${NC}"
    exit 1
fi

echo ""
echo "=========================================="
echo -e "${GREEN}Backup complete!${NC}"
echo "=========================================="
echo ""
echo "To restore this backup:"
echo "  ./scripts/rollback_patterns.sh $BACKUP_FILE"
echo ""

# List recent backups
echo "Recent backups:"
ls -lht "$BACKUP_DIR" | grep "backup_patterns" | head -5

exit 0
