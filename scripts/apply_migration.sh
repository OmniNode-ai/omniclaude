#!/usr/bin/env bash
# Apply database migrations
# Usage: ./scripts/apply_migration.sh <migration_file>

set -euo pipefail

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

# Configuration (no fallbacks - must be set in .env)
DB_HOST="${POSTGRES_HOST}"
DB_PORT="${POSTGRES_PORT}"
DB_NAME="${POSTGRES_DATABASE}"
DB_USER="${POSTGRES_USER}"
DB_PASSWORD="${POSTGRES_PASSWORD}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Verify required variables are set
missing_vars=()
[ -z "$DB_HOST" ] && missing_vars+=("POSTGRES_HOST")
[ -z "$DB_PORT" ] && missing_vars+=("POSTGRES_PORT")
[ -z "$DB_NAME" ] && missing_vars+=("POSTGRES_DATABASE")
[ -z "$DB_USER" ] && missing_vars+=("POSTGRES_USER")
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

# Help
if [ $# -eq 0 ] || [ "$1" == "--help" ] || [ "$1" == "-h" ]; then
    echo "Usage: $0 <migration_file>"
    echo ""
    echo "Example:"
    echo "  $0 agents/migrations/001_agent_detection_failures.sql"
    echo ""
    echo "Environment variables (configured in .env):"
    echo "  POSTGRES_HOST (required)"
    echo "  POSTGRES_PORT (required)"
    echo "  POSTGRES_DATABASE (required)"
    echo "  POSTGRES_USER (required)"
    echo "  POSTGRES_PASSWORD (required)"
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
