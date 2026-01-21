#!/bin/bash
# Query Recent Routing Decisions - Quick Observability Check

set -e

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

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

# Configuration (no fallbacks - must be set in .env)
POSTGRES_HOST="${POSTGRES_HOST}"
POSTGRES_PORT="${POSTGRES_PORT}"
POSTGRES_USER="${POSTGRES_USER}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD}"
POSTGRES_DB="${POSTGRES_DATABASE}"
LIMIT=${1:-20}

# Verify required variables are set
missing_vars=()
[ -z "$POSTGRES_HOST" ] && missing_vars+=("POSTGRES_HOST")
[ -z "$POSTGRES_PORT" ] && missing_vars+=("POSTGRES_PORT")
[ -z "$POSTGRES_USER" ] && missing_vars+=("POSTGRES_USER")
[ -z "$POSTGRES_PASSWORD" ] && missing_vars+=("POSTGRES_PASSWORD")
[ -z "$POSTGRES_DB" ] && missing_vars+=("POSTGRES_DATABASE")

if [ ${#missing_vars[@]} -gt 0 ]; then
    echo -e "${RED}❌ ERROR: Required environment variables not set in .env:${NC}"
    for var in "${missing_vars[@]}"; do
        echo "   - $var"
    done
    echo ""
    echo "Please update your .env file with these variables."
    exit 1
fi

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}📊 Recent Routing Decisions${NC}"
echo -e "${BLUE}========================================${NC}\n"

echo -e "${CYAN}Showing last $LIMIT routing decisions...${NC}\n"

# Query recent routing decisions
QUERY="
SELECT
    LEFT(correlation_id::text, 8) || '...' as corr_id,
    selected_agent,
    ROUND(confidence_score::numeric, 2) as confidence,
    routing_strategy,
    routing_time_ms as latency_ms,
    LEFT(user_request, 50) || '...' as request,
    project_name,
    created_at AT TIME ZONE 'UTC' as created_utc
FROM agent_routing_decisions
ORDER BY created_at DESC
LIMIT $LIMIT;
"

PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "$QUERY"

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}✅ Query Complete${NC}"
echo -e "${GREEN}========================================${NC}\n"

echo -e "${YELLOW}💡 Tip: Use ./scripts/trace-correlation-id.sh <correlation-id> for full trace${NC}\n"

exit 0
