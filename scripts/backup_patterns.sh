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

# Load environment variables from .env
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
    echo "❌ ERROR: .env file not found at $PROJECT_ROOT/.env"
    echo "   Please copy .env.example to .env and configure it"
    exit 1
fi

# Source .env file
source "$PROJECT_ROOT/.env"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Configuration (no fallbacks - must be set in .env)
DB_HOST="${POSTGRES_HOST}"
DB_PORT="${POSTGRES_PORT}"
DB_USER="${POSTGRES_USER}"
DB_NAME="${POSTGRES_DATABASE}"
DB_PASSWORD="${POSTGRES_PASSWORD}"

# Verify required variables are set
missing_vars=()
[ -z "$DB_HOST" ] && missing_vars+=("POSTGRES_HOST")
[ -z "$DB_PORT" ] && missing_vars+=("POSTGRES_PORT")
[ -z "$DB_USER" ] && missing_vars+=("POSTGRES_USER")
[ -z "$DB_NAME" ] && missing_vars+=("POSTGRES_DATABASE")
[ -z "$DB_PASSWORD" ] && missing_vars+=("POSTGRES_PASSWORD")

if [ ${#missing_vars[@]} -gt 0 ]; then
    echo -e "${RED}❌ ERROR: Required environment variables not set in .env:${NC}"
    for var in "${missing_vars[@]}"; do
        echo "   - $var"
    done
    echo ""
    echo "Please update your .env file with these variables."
    exit 1
fi

# Generate timestamped backup filename
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="./backups"
BACKUP_FILE="${BACKUP_DIR}/backup_patterns_${TIMESTAMP}.sql"

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
