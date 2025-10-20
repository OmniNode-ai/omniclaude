#!/usr/bin/env bash
# Apply database migrations
# Usage: ./scripts/apply_migration.sh <migration_file>

set -euo pipefail

# Configuration
DB_HOST="${OMNINODE_BRIDGE_HOST:-localhost}"
DB_PORT="${OMNINODE_BRIDGE_PORT:-5436}"
DB_NAME="${OMNINODE_BRIDGE_DB:-omninode_bridge}"
DB_USER="${OMNINODE_BRIDGE_USER:-postgres}"
DB_PASSWORD="${OMNINODE_BRIDGE_PASSWORD:-omninode-bridge-postgres-dev-2024}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Help
if [ $# -eq 0 ] || [ "$1" == "--help" ] || [ "$1" == "-h" ]; then
    echo "Usage: $0 <migration_file>"
    echo ""
    echo "Example:"
    echo "  $0 agents/migrations/001_agent_detection_failures.sql"
    echo ""
    echo "Environment variables:"
    echo "  OMNINODE_BRIDGE_HOST     (default: localhost)"
    echo "  OMNINODE_BRIDGE_PORT     (default: 5436)"
    echo "  OMNINODE_BRIDGE_DB       (default: omninode_bridge)"
    echo "  OMNINODE_BRIDGE_USER     (default: postgres)"
    echo "  OMNINODE_BRIDGE_PASSWORD (default: omninode-bridge-postgres-dev-2024)"
    exit 0
fi

MIGRATION_FILE="$1"

# Validate migration file exists
if [ ! -f "$MIGRATION_FILE" ]; then
    echo -e "${RED}❌ Error: Migration file not found: $MIGRATION_FILE${NC}"
    exit 1
fi

echo -e "${YELLOW}🔧 Applying migration: $MIGRATION_FILE${NC}"
echo "  Database: $DB_USER@$DB_HOST:$DB_PORT/$DB_NAME"
echo ""

# Apply migration
if PGPASSWORD="$DB_PASSWORD" psql \
    -h "$DB_HOST" \
    -p "$DB_PORT" \
    -U "$DB_USER" \
    -d "$DB_NAME" \
    -f "$MIGRATION_FILE"; then
    echo ""
    echo -e "${GREEN}✅ Migration applied successfully!${NC}"
else
    echo ""
    echo -e "${RED}❌ Migration failed!${NC}"
    exit 1
fi

# If this is the detection failures migration, show helpful queries
if [[ "$MIGRATION_FILE" == *"agent_detection_failures"* ]]; then
    echo ""
    echo -e "${YELLOW}📊 Helpful queries for the new table:${NC}"
    echo ""
    echo "# View detection failure patterns:"
    echo "SELECT * FROM agent_detection_failure_patterns;"
    echo ""
    echo "# View unreviewed failures:"
    echo "SELECT * FROM agent_detection_failures_to_review;"
    echo ""
    echo "# View low confidence detections:"
    echo "SELECT * FROM agent_low_confidence_detections;"
    echo ""
    echo "# Get failure statistics (last 24 hours):"
    echo "SELECT * FROM get_detection_failure_stats(24);"
    echo ""
    echo "# Mark a failure as reviewed:"
    echo "SELECT mark_detection_failure_reviewed(1, 'admin', 'agent-workflow-coordinator', 'Should have detected coordinator');"
    echo ""
fi
