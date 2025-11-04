#!/bin/bash
# Query Recent Routing Decisions - Quick Observability Check

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Configuration
POSTGRES_HOST=${POSTGRES_HOST:-"192.168.86.200"}
POSTGRES_PORT=${POSTGRES_PORT:-"5436"}
POSTGRES_USER=${POSTGRES_USER:-"postgres"}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}  # Must be set in environment
POSTGRES_DB=${POSTGRES_DATABASE:-"omninode_bridge"}
LIMIT=${1:-20}

# Verify password is set
if [ -z "$POSTGRES_PASSWORD" ]; then
    echo "❌ ERROR: POSTGRES_PASSWORD environment variable not set"
    echo "   Please run: source .env"
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
