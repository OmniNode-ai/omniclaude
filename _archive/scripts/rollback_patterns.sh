#!/bin/bash
################################################################################
# Pattern System Rollback Script
################################################################################
# Purpose: Restore pattern system from backup
# Usage: ./scripts/rollback_patterns.sh <backup_file>
# Example: ./scripts/rollback_patterns.sh backups/backup_patterns_20251028_143000.sql
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
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration (no fallbacks - must be set in .env)
DB_HOST="${POSTGRES_HOST}"
DB_PORT="${POSTGRES_PORT}"
DB_USER="${POSTGRES_USER}"
DB_NAME="${POSTGRES_DATABASE}"
# Note: Using POSTGRES_PASSWORD directly (no alias)

# Verify required variables are set
missing_vars=()
[ -z "$DB_HOST" ] && missing_vars+=("POSTGRES_HOST")
[ -z "$DB_PORT" ] && missing_vars+=("POSTGRES_PORT")
[ -z "$DB_USER" ] && missing_vars+=("POSTGRES_USER")
[ -z "$DB_NAME" ] && missing_vars+=("POSTGRES_DATABASE")
[ -z "$POSTGRES_PASSWORD" ] && missing_vars+=("POSTGRES_PASSWORD")

if [ ${#missing_vars[@]} -gt 0 ]; then
    echo -e "${RED}❌ ERROR: Required environment variables not set in .env:${NC}"
    for var in "${missing_vars[@]}"; do
        echo "   - $var"
    done
    echo ""
    echo "Please update your .env file with these variables."
    exit 1
fi

################################################################################
# Argument validation
################################################################################

if [ $# -eq 0 ]; then
    echo -e "${RED}Error: Backup file not specified${NC}"
    echo ""
    echo "Usage: $0 <backup_file>"
    echo ""
    echo "Available backups:"
    if [ -d "./backups" ]; then
        ls -lht ./backups | grep "backup_patterns" | head -10
    else
        echo "  (no backups directory found)"
    fi
    echo ""
    exit 1
fi

BACKUP_FILE="$1"

if [ ! -f "$BACKUP_FILE" ]; then
    echo -e "${RED}Error: Backup file not found: $BACKUP_FILE${NC}"
    echo ""
    echo "Available backups:"
    if [ -d "./backups" ]; then
        ls -lht ./backups | grep "backup_patterns" | head -10
    else
        echo "  (no backups directory found)"
    fi
    echo ""
    exit 1
fi

################################################################################
# Display backup information
################################################################################

echo ""
echo "=========================================="
echo "Pattern System Rollback"
echo "=========================================="
echo ""
echo "Database: $DB_NAME @ $DB_HOST:$DB_PORT"
echo "Backup file: $BACKUP_FILE"
echo ""

# Show backup file info
BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
BACKUP_DATE=$(stat -f "%Sm" -t "%Y-%m-%d %H:%M:%S" "$BACKUP_FILE" 2>/dev/null || stat -c "%y" "$BACKUP_FILE" 2>/dev/null || echo "Unknown")
LINE_COUNT=$(wc -l < "$BACKUP_FILE")

echo "Backup Information:"
echo "  Size: $BACKUP_SIZE"
echo "  Created: $BACKUP_DATE"
echo "  Lines: $LINE_COUNT"
echo ""

# Verify checksum if available
if [ -f "${BACKUP_FILE}.md5" ]; then
    echo -e "${YELLOW}Verifying backup integrity...${NC}"
    if command -v md5 &> /dev/null; then
        CURRENT_MD5=$(md5 -q "$BACKUP_FILE")
        EXPECTED_MD5=$(cat "${BACKUP_FILE}.md5" | cut -d' ' -f1)
        if [ "$CURRENT_MD5" = "$EXPECTED_MD5" ]; then
            echo -e "${GREEN}✓ Checksum verified${NC}"
        else
            echo -e "${RED}✗ Checksum mismatch! Backup may be corrupted.${NC}"
            echo "  Expected: $EXPECTED_MD5"
            echo "  Actual: $CURRENT_MD5"
            read -p "Continue anyway? (yes/no): " continue_anyway
            if [ "$continue_anyway" != "yes" ]; then
                echo "Rollback cancelled"
                exit 1
            fi
        fi
    elif command -v md5sum &> /dev/null; then
        if md5sum -c "${BACKUP_FILE}.md5" 2>&1 | grep -q OK; then
            echo -e "${GREEN}✓ Checksum verified${NC}"
        else
            echo -e "${RED}✗ Checksum mismatch! Backup may be corrupted.${NC}"
            read -p "Continue anyway? (yes/no): " continue_anyway
            if [ "$continue_anyway" != "yes" ]; then
                echo "Rollback cancelled"
                exit 1
            fi
        fi
    fi
    echo ""
fi

################################################################################
# Current state backup
################################################################################

echo -e "${YELLOW}Current pattern counts (before rollback):${NC}"
PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c "
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
" 2>/dev/null || echo "  (unable to query current state)"

echo ""

################################################################################
# Confirmation
################################################################################

echo -e "${RED}⚠️  WARNING: This will DELETE all current pattern data!${NC}"
echo ""
echo "This action will:"
echo "  1. Truncate all pattern tables (pattern_lineage_nodes, pattern_lineage_edges, pattern_relationships)"
echo "  2. Restore data from backup file"
echo "  3. Cannot be undone (unless you create a new backup first)"
echo ""
read -p "Are you ABSOLUTELY sure you want to rollback? Type 'yes' to confirm: " confirm

if [ "$confirm" != "yes" ]; then
    echo -e "${YELLOW}Rollback cancelled by user${NC}"
    exit 0
fi

echo ""

################################################################################
# Create safety backup of current state
################################################################################

echo -e "${YELLOW}Creating safety backup of current state...${NC}"
SAFETY_BACKUP="./backups/pre_rollback_$(date +%Y%m%d_%H%M%S).sql"

PGPASSWORD="$POSTGRES_PASSWORD" pg_dump \
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
  --file="$SAFETY_BACKUP" 2>/dev/null || {
    echo -e "${YELLOW}⚠ Safety backup failed (continuing anyway)${NC}"
}

if [ -f "$SAFETY_BACKUP" ]; then
    echo -e "${GREEN}✓ Safety backup created: $SAFETY_BACKUP${NC}"
else
    echo -e "${YELLOW}⚠ No safety backup created${NC}"
fi

echo ""

################################################################################
# Truncate tables
################################################################################

echo -e "${YELLOW}Truncating pattern tables...${NC}"

PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" <<EOF
-- Truncate tables (cascade to handle foreign keys)
TRUNCATE TABLE pattern_relationships CASCADE;
TRUNCATE TABLE pattern_lineage_edges CASCADE;
TRUNCATE TABLE pattern_lineage_nodes CASCADE;

-- Verify truncation
SELECT
  'pattern_lineage_nodes: ' || COUNT(*) as status
FROM pattern_lineage_nodes
UNION ALL
SELECT
  'pattern_lineage_edges: ' || COUNT(*)
FROM pattern_lineage_edges
UNION ALL
SELECT
  'pattern_relationships: ' || COUNT(*)
FROM pattern_relationships;
EOF

echo -e "${GREEN}✓ Tables truncated${NC}"
echo ""

################################################################################
# Restore from backup
################################################################################

echo -e "${YELLOW}Restoring from backup...${NC}"

if PGPASSWORD="$POSTGRES_PASSWORD" psql \
    -h "$DB_HOST" \
    -p "$DB_PORT" \
    -U "$DB_USER" \
    -d "$DB_NAME" \
    -f "$BACKUP_FILE" > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Backup restored successfully${NC}"
else
    echo -e "${RED}✗ Restore failed!${NC}"
    echo ""
    echo "Attempting to restore from safety backup..."
    if [ -f "$SAFETY_BACKUP" ]; then
        PGPASSWORD="$POSTGRES_PASSWORD" psql \
            -h "$DB_HOST" \
            -p "$DB_PORT" \
            -U "$DB_USER" \
            -d "$DB_NAME" \
            -f "$SAFETY_BACKUP" > /dev/null 2>&1 && {
            echo -e "${GREEN}✓ Safety backup restored${NC}"
        } || {
            echo -e "${RED}✗ Safety backup restore also failed!${NC}"
            echo "Database may be in inconsistent state!"
            exit 1
        }
    else
        echo -e "${RED}No safety backup available!${NC}"
        exit 1
    fi
fi

echo ""

################################################################################
# Verify restoration
################################################################################

echo -e "${YELLOW}Verifying restoration...${NC}"
echo ""

PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" <<EOF
SELECT
  'pattern_lineage_nodes: ' || COUNT(*) as counts
FROM pattern_lineage_nodes
UNION ALL
SELECT
  'pattern_lineage_edges: ' || COUNT(*)
FROM pattern_lineage_edges
UNION ALL
SELECT
  'pattern_relationships: ' || COUNT(*)
FROM pattern_relationships;
EOF

echo ""

################################################################################
# Final summary
################################################################################

echo "=========================================="
echo -e "${GREEN}Rollback Complete!${NC}"
echo "=========================================="
echo ""
echo "Restored from: $BACKUP_FILE"
if [ -f "$SAFETY_BACKUP" ]; then
    echo "Safety backup: $SAFETY_BACKUP"
fi
echo ""
echo "Next steps:"
echo "  1. Verify data with: ./scripts/validate_patterns.sh"
echo "  2. Test pattern queries in your application"
echo ""

exit 0
