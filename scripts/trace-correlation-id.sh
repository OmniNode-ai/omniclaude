#!/bin/bash
# Correlation ID Tracing Script - Complete Observability
# Traces a correlation ID through the entire logging pipeline

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m'

# Configuration
POSTGRES_HOST=${POSTGRES_HOST:-"192.168.86.200"}
POSTGRES_PORT=${POSTGRES_PORT:-"5436"}
POSTGRES_USER=${POSTGRES_USER:-"postgres"}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}  # Must be set in environment
POSTGRES_DB=${POSTGRES_DATABASE:-"omninode_bridge"}

# Verify password is set
if [ -z "$POSTGRES_PASSWORD" ]; then
    echo -e "${RED}❌ ERROR: POSTGRES_PASSWORD environment variable not set${NC}"
    echo "   Please run: source .env"
    exit 1
fi

# Usage
if [ $# -lt 1 ]; then
    echo -e "${YELLOW}Usage: $0 <correlation-id> [--kafka] [--verbose]${NC}"
    echo ""
    echo "Examples:"
    echo "  $0 8fc02178-6243-4f96-86f1-ba3ff737b791"
    echo "  $0 8fc02178-6243-4f96-86f1-ba3ff737b791 --kafka --verbose"
    echo ""
    echo "Options:"
    echo "  --kafka     Also check Kafka events (requires redpanda container)"
    echo "  --verbose   Show detailed SQL queries"
    exit 1
fi

CORRELATION_ID="$1"
CHECK_KAFKA=false
VERBOSE=false

# Parse options
shift
while [ $# -gt 0 ]; do
    case "$1" in
        --kafka) CHECK_KAFKA=true ;;
        --verbose) VERBOSE=true ;;
        *) echo -e "${RED}Unknown option: $1${NC}"; exit 1 ;;
    esac
    shift
done

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}🔍 Correlation ID Trace${NC}"
echo -e "${BLUE}========================================${NC}\n"
echo -e "${CYAN}Correlation ID: $CORRELATION_ID${NC}\n"

# Function to run SQL query
run_query() {
    local query="$1"
    local description="$2"

    if [ "$VERBOSE" = true ]; then
        echo -e "${MAGENTA}Query: $query${NC}\n"
    fi

    echo -e "${YELLOW}▶ $description${NC}"

    PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" \
        -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$query" 2>&1

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}  ✅ Query successful${NC}\n"
    else
        echo -e "${RED}  ❌ Query failed${NC}\n"
    fi
}

# 1. Routing Decision
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}1. ROUTING DECISION${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"

ROUTING_QUERY="
SELECT
    id,
    selected_agent,
    confidence_score,
    routing_strategy,
    routing_time_ms,
    user_request,
    reasoning,
    alternatives::text,
    created_at,
    project_name,
    session_id
FROM agent_routing_decisions
WHERE correlation_id = '$CORRELATION_ID'
ORDER BY created_at DESC;
"

run_query "$ROUTING_QUERY" "Routing Decision"

# 2. Agent Actions
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}2. AGENT ACTIONS${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"

ACTIONS_QUERY="
SELECT
    id,
    agent_name,
    action_type,
    action_name,
    duration_ms,
    action_details::text,
    created_at
FROM agent_actions
WHERE correlation_id = '$CORRELATION_ID'
ORDER BY created_at ASC;
"

run_query "$ACTIONS_QUERY" "Agent Actions (chronological)"

# 3. Agent Transformations
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}3. AGENT TRANSFORMATIONS${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"

TRANSFORM_QUERY="
SELECT
    id,
    source_agent,
    target_agent,
    confidence_score,
    transformation_reason,
    transformation_duration_ms,
    success,
    created_at
FROM agent_transformation_events
WHERE correlation_id = '$CORRELATION_ID'
ORDER BY created_at ASC;
"

run_query "$TRANSFORM_QUERY" "Agent Transformations"

# 4. Performance Metrics
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}4. PERFORMANCE METRICS${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"

METRICS_QUERY="
SELECT
    id,
    query_text,
    routing_duration_ms,
    cache_hit,
    trigger_match_strategy,
    candidates_evaluated,
    confidence_components::text,
    created_at
FROM router_performance_metrics
WHERE correlation_id = '$CORRELATION_ID'
ORDER BY created_at ASC;
"

run_query "$METRICS_QUERY" "Performance Metrics"

# 5. Agent Execution Logs (if table exists)
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}5. AGENT EXECUTION LOGS${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"

EXECUTION_QUERY="
SELECT
    execution_id,
    agent_name,
    status,
    quality_score,
    duration_ms,
    start_time,
    end_time,
    error_message
FROM agent_execution_logs
WHERE correlation_id = '$CORRELATION_ID'
ORDER BY start_time ASC;
"

run_query "$EXECUTION_QUERY" "Execution Logs" || echo -e "${YELLOW}  ℹ️  agent_execution_logs table may not exist${NC}\n"

# 6. Manifest Injections (if table exists)
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}6. MANIFEST INJECTIONS${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"

MANIFEST_QUERY="
SELECT
    agent_name,
    patterns_count,
    debug_intelligence_successes,
    debug_intelligence_failures,
    total_query_time_ms,
    created_at
FROM agent_manifest_injections
WHERE correlation_id = '$CORRELATION_ID'
ORDER BY created_at DESC;
"

run_query "$MANIFEST_QUERY" "Manifest Injections" || echo -e "${YELLOW}  ℹ️  agent_manifest_injections table may not exist${NC}\n"

# 7. Check Kafka Events (if requested)
if [ "$CHECK_KAFKA" = true ]; then
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}7. KAFKA EVENTS${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"

    echo -e "${YELLOW}▶ Searching Kafka topics for correlation ID...${NC}"

    # Check agent-routing-decisions topic
    echo -e "${MAGENTA}Topic: agent-routing-decisions${NC}"
    docker exec omninode-bridge-redpanda-dev rpk topic consume agent-routing-decisions \
        --num 1000 --offset start --format '%v' 2>/dev/null | \
        grep "$CORRELATION_ID" | jq '.' 2>/dev/null || echo -e "${YELLOW}  No events found${NC}"

    # Check agent-actions topic
    echo -e "\n${MAGENTA}Topic: agent-actions${NC}"
    docker exec omninode-bridge-redpanda-dev rpk topic consume agent-actions \
        --num 1000 --offset start --format '%v' 2>/dev/null | \
        grep "$CORRELATION_ID" | jq '.' 2>/dev/null || echo -e "${YELLOW}  No events found${NC}"

    # Check agent-transformation-events topic
    echo -e "\n${MAGENTA}Topic: agent-transformation-events${NC}"
    docker exec omninode-bridge-redpanda-dev rpk topic consume agent-transformation-events \
        --num 1000 --offset start --format '%v' 2>/dev/null | \
        grep "$CORRELATION_ID" | jq '.' 2>/dev/null || echo -e "${YELLOW}  No events found${NC}"

    # Check router-performance-metrics topic
    echo -e "\n${MAGENTA}Topic: router-performance-metrics${NC}"
    docker exec omninode-bridge-redpanda-dev rpk topic consume router-performance-metrics \
        --num 1000 --offset start --format '%v' 2>/dev/null | \
        grep "$CORRELATION_ID" | jq '.' 2>/dev/null || echo -e "${YELLOW}  No events found${NC}"

    echo ""
fi

# Summary
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}✅ Trace Complete${NC}"
echo -e "${GREEN}========================================${NC}\n"

echo -e "${BLUE}📊 Summary:${NC}"
echo -e "  Correlation ID:    $CORRELATION_ID"
echo -e "  Database:          ${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}"
echo -e "  Kafka Events:      $([ "$CHECK_KAFKA" = true ] && echo "Checked" || echo "Not checked (use --kafka)")"
echo ""

exit 0
