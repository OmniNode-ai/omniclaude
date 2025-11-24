#!/usr/bin/env bash
# Apply migration 015: Add unique constraint to agent_actions table
# Usage: ./scripts/apply_migration_015.sh
# Requires: .env file with PostgreSQL credentials

set -euo pipefail

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "========================================================================"
echo "Migration 015: Add unique constraint to agent_actions table"
echo "========================================================================"
echo ""

# Check if .env exists
if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
    echo -e "${RED}❌ Error: .env file not found${NC}"
    echo "Please create .env file with PostgreSQL credentials"
    echo "Example: cp .env.example .env"
    exit 1
fi

# Load environment variables
set -a
source "$PROJECT_ROOT/.env"
set +a

# Verify required variables
if [[ -z "${POSTGRES_HOST:-}" ]] || [[ -z "${POSTGRES_PORT:-}" ]] || \
   [[ -z "${POSTGRES_USER:-}" ]] || [[ -z "${POSTGRES_PASSWORD:-}" ]] || \
   [[ -z "${POSTGRES_DATABASE:-}" ]]; then
    echo -e "${RED}❌ Error: Missing required PostgreSQL environment variables${NC}"
    echo "Required: POSTGRES_HOST, POSTGRES_PORT, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DATABASE"
    exit 1
fi

echo -e "${GREEN}✅ Environment variables loaded${NC}"
echo "  Host: $POSTGRES_HOST"
echo "  Port: $POSTGRES_PORT"
echo "  Database: $POSTGRES_DATABASE"
echo "  User: $POSTGRES_USER"
echo ""

# Migration file
MIGRATION_FILE="$PROJECT_ROOT/migrations/015_add_agent_actions_unique_constraint.sql"

if [[ ! -f "$MIGRATION_FILE" ]]; then
    echo -e "${RED}❌ Error: Migration file not found: $MIGRATION_FILE${NC}"
    exit 1
fi

echo -e "${YELLOW}📋 Migration file:${NC} $MIGRATION_FILE"
echo ""

# Check if psql is available
if ! command -v psql &> /dev/null; then
    echo -e "${RED}❌ Error: psql command not found${NC}"
    echo "Please install PostgreSQL client tools"
    exit 1
fi

# Test database connection
echo -e "${YELLOW}🔍 Testing database connection...${NC}"
if ! PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" \
     -U "$POSTGRES_USER" -d "$POSTGRES_DATABASE" -c "SELECT 1" > /dev/null 2>&1; then
    echo -e "${RED}❌ Error: Cannot connect to database${NC}"
    echo "Please check your database credentials and network connectivity"
    exit 1
fi
echo -e "${GREEN}✅ Database connection successful${NC}"
echo ""

# Check if constraint already exists
echo -e "${YELLOW}🔍 Checking if constraint already exists...${NC}"
CONSTRAINT_EXISTS=$(PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" \
    -U "$POSTGRES_USER" -d "$POSTGRES_DATABASE" -t -c \
    "SELECT COUNT(*) FROM information_schema.table_constraints
     WHERE table_name = 'agent_actions'
       AND constraint_name = 'unique_action_per_correlation_timestamp'
       AND constraint_type = 'UNIQUE'" | xargs)

if [[ "$CONSTRAINT_EXISTS" -gt 0 ]]; then
    echo -e "${YELLOW}⚠️  Warning: Constraint already exists${NC}"
    echo "The unique constraint 'unique_action_per_correlation_timestamp' is already present"
    echo ""
    read -p "Do you want to continue anyway? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Migration aborted"
        exit 0
    fi
fi

# Apply migration
echo -e "${YELLOW}🚀 Applying migration...${NC}"
echo ""

if PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" \
   -U "$POSTGRES_USER" -d "$POSTGRES_DATABASE" -f "$MIGRATION_FILE"; then
    echo ""
    echo -e "${GREEN}✅ Migration applied successfully!${NC}"
    echo ""

    # Verify constraint exists
    echo -e "${YELLOW}🔍 Verifying constraint...${NC}"
    CONSTRAINT_CHECK=$(PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" \
        -U "$POSTGRES_USER" -d "$POSTGRES_DATABASE" -t -c \
        "SELECT constraint_name FROM information_schema.table_constraints
         WHERE table_name = 'agent_actions'
           AND constraint_name = 'unique_action_per_correlation_timestamp'
           AND constraint_type = 'UNIQUE'")

    if [[ -n "$CONSTRAINT_CHECK" ]]; then
        echo -e "${GREEN}✅ Constraint verified: unique_action_per_correlation_timestamp${NC}"
    else
        echo -e "${RED}❌ Warning: Constraint verification failed${NC}"
        exit 1
    fi

    echo ""
    echo "========================================================================"
    echo "Next steps:"
    echo "  1. Restart Kafka consumers: docker-compose restart agent-consumer"
    echo "  2. Run tests: python3 tests/test_agent_actions_unique_constraint.py"
    echo "  3. Monitor logs for duplicate prevention messages"
    echo ""
    echo "To rollback:"
    echo "  psql ... -f migrations/015_rollback_agent_actions_unique_constraint.sql"
    echo "========================================================================"
else
    echo ""
    echo -e "${RED}❌ Migration failed!${NC}"
    echo "Please check the error messages above"
    exit 1
fi
