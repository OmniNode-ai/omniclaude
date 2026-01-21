#!/bin/bash
################################################################################
# test_agent_execution.sh
#
# Purpose: End-to-end test of agent execution logging pipeline
#
# What it does:
# 1. Trigger a test agent execution with generated correlation ID
# 2. Verify logging works end-to-end (Agent → Kafka → Consumer → DB)
# 3. Check database receives all expected data
# 4. Measure end-to-end latency
# 5. Validate data integrity and completeness
#
# Usage:
#   ./test_agent_execution.sh
#   ./test_agent_execution.sh --keep-data     # Don't clean up test data
#   ./test_agent_execution.sh --timeout 30    # Custom timeout in seconds
#
# Prerequisites:
#   - PostgreSQL credentials in .env file
#   - Docker access (for checking Kafka)
#   - Agent tracking skills available
#   - Kafka broker running
#
# Environment Variables (configured in .env):
#   POSTGRES_HOST (required)
#   POSTGRES_PORT (required)
#   POSTGRES_USER (required)
#   POSTGRES_PASSWORD (required)
#   POSTGRES_DATABASE (required)
#   KAFKA_BOOTSTRAP_SERVERS (required)
#
# Exit Codes:
#   0 - Test passed successfully
#   1 - Test failed
#
# Created: 2025-10-29
################################################################################

set -o pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CORRELATION_ID="test-exec-$(date +%s)-$$"
KEEP_DATA=false
TIMEOUT=30  # seconds
TEST_FAILED=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --keep-data|-k)
            KEEP_DATA=true
            shift
            ;;
        --timeout|-t)
            TIMEOUT="$2"
            shift 2
            ;;
        --help|-h)
            grep "^#" "$0" | grep -v "^#!/" | sed 's/^# //' | sed 's/^#//'
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Load environment
if [ ! -f "$PROJECT_ROOT/.env" ]; then
    echo -e "${RED}❌ ERROR: .env file not found at $PROJECT_ROOT/.env${NC}"
    echo "   Please copy .env.example to .env and configure it"
    exit 1
fi

set -a
source "$PROJECT_ROOT/.env"
set +a

# Configuration (no fallbacks - must be set in .env)
POSTGRES_HOST="${POSTGRES_HOST}"
POSTGRES_PORT="${POSTGRES_PORT}"
POSTGRES_USER="${POSTGRES_USER}"
POSTGRES_DB="${POSTGRES_DATABASE}"
KAFKA_BOOTSTRAP_SERVERS="${KAFKA_BOOTSTRAP_SERVERS}"
export PGPASSWORD="${POSTGRES_PASSWORD}"

# Verify required variables are set
missing_vars=()
[ -z "$POSTGRES_HOST" ] && missing_vars+=("POSTGRES_HOST")
[ -z "$POSTGRES_PORT" ] && missing_vars+=("POSTGRES_PORT")
[ -z "$POSTGRES_USER" ] && missing_vars+=("POSTGRES_USER")
[ -z "$POSTGRES_DB" ] && missing_vars+=("POSTGRES_DATABASE")
[ -z "$PGPASSWORD" ] && missing_vars+=("POSTGRES_PASSWORD")
[ -z "$KAFKA_BOOTSTRAP_SERVERS" ] && missing_vars+=("KAFKA_BOOTSTRAP_SERVERS")

if [ ${#missing_vars[@]} -gt 0 ]; then
    echo -e "${RED}❌ ERROR: Required environment variables not set in .env:${NC}"
    for var in "${missing_vars[@]}"; do
        echo "   - $var"
    done
    echo ""
    echo "Please update your .env file with these variables."
    exit 1
fi

# Helper functions
log_info() {
    echo -e "${CYAN}ℹ${NC}  $1"
}

log_success() {
    echo -e "${GREEN}✅${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}⚠️${NC}  $1"
}

log_error() {
    echo -e "${RED}❌${NC} $1"
    TEST_FAILED=true
}

log_step() {
    echo ""
    echo -e "${BLUE}▶ STEP $1${NC}"
}

section_header() {
    echo ""
    echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
}

wait_for_condition() {
    local description="$1"
    local check_command="$2"
    local timeout_seconds="$3"
    local interval=0.5

    local elapsed=0
    while [ $(echo "$elapsed < $timeout_seconds" | bc -l) -eq 1 ]; do
        if eval "$check_command" &> /dev/null; then
            return 0
        fi
        sleep $interval
        elapsed=$(echo "$elapsed + $interval" | bc -l)
    done

    log_error "$description: timeout after ${timeout_seconds}s"
    return 1
}

# Cleanup function
cleanup() {
    if [ "$KEEP_DATA" = false ]; then
        log_info "Cleaning up test data..."

        # Delete from all tables
        psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
            -c "DELETE FROM agent_actions WHERE correlation_id::text = '$CORRELATION_ID';" &> /dev/null

        psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
            -c "DELETE FROM agent_execution_logs WHERE correlation_id::text = '$CORRELATION_ID';" &> /dev/null

        psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
            -c "DELETE FROM agent_manifest_injections WHERE correlation_id::text = '$CORRELATION_ID';" &> /dev/null

        log_success "Test data cleaned up"
    else
        log_info "Test data retained (correlation_id: $CORRELATION_ID)"
    fi
}

trap cleanup EXIT

# Main test flow
echo -e "${CYAN}"
echo "╔═════════════════════════════════════════════════════════════════╗"
echo "║       Agent Execution End-to-End Test                           ║"
echo "╚═════════════════════════════════════════════════════════════════╝"
echo -e "${NC}"
echo "Started: $(date '+%Y-%m-%d %H:%M:%S')"
echo "Correlation ID: $CORRELATION_ID"
echo ""

# Prerequisite checks
section_header "PREREQUISITE CHECKS"

log_info "Checking database connection..."
if ! psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "SELECT 1" &> /dev/null; then
    log_error "Cannot connect to database"
    exit 1
fi
log_success "Database connection OK"

log_info "Checking agent tracking skills..."
if [ ! -f "$PROJECT_ROOT/skills/agent-tracking/log-agent-action/execute_kafka.py" ]; then
    log_error "Agent tracking skills not found"
    exit 1
fi
log_success "Agent tracking skills found"

# Test execution
section_header "TEST EXECUTION"

log_step "1: Publish test agent actions"

START_TIME=$(date +%s.%N)

# Simulate agent workflow: 5 actions
ACTIONS=(
    "decision:analyze_request:150:{\"request\":\"test execution\",\"complexity\":\"low\"}"
    "tool_call:Read:25:{\"file_path\":\"test.py\",\"lines\":50}"
    "tool_call:Write:45:{\"file_path\":\"output.py\",\"bytes\":1024}"
    "tool_call:Bash:100:{\"command\":\"echo test\",\"exit_code\":0}"
    "success:task_completed:10:{\"total_duration_ms\":330}"
)

for i in "${!ACTIONS[@]}"; do
    IFS=':' read -r action_type action_name duration_ms details <<< "${ACTIONS[$i]}"

    python3 "$PROJECT_ROOT/skills/agent-tracking/log-agent-action/execute_kafka.py" \
        --agent "test-agent-e2e" \
        --action-type "$action_type" \
        --action-name "$action_name" \
        --correlation-id "$CORRELATION_ID" \
        --details "$details" \
        --duration-ms "$duration_ms" \
        --debug-mode &> /dev/null

    if [ $? -eq 0 ]; then
        log_success "Action $((i+1))/5: $action_name logged to Kafka"
    else
        log_error "Action $((i+1))/5: failed to log $action_name"
    fi

    sleep 0.2  # Small delay between actions
done

log_step "2: Wait for consumer to process events"

log_info "Waiting for actions to appear in database (timeout: ${TIMEOUT}s)..."

# Wait for all 5 actions to be in database
if wait_for_condition "Database persistence" \
    "[ \$(psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DB -tAc \"SELECT COUNT(*) FROM agent_actions WHERE correlation_id::text = '$CORRELATION_ID';\" 2>/dev/null || echo 0) -ge 5 ]" \
    "$TIMEOUT"; then

    END_TIME=$(date +%s.%N)
    LATENCY=$(echo "$END_TIME - $START_TIME" | bc -l)
    LATENCY_MS=$(printf "%.0f" $(echo "$LATENCY * 1000" | bc -l))

    log_success "All 5 actions persisted to database"
    log_info "End-to-end latency: ${LATENCY_MS}ms"

    if [ "$LATENCY_MS" -lt 5000 ]; then
        log_success "Latency within 5s target"
    else
        log_warning "Latency ${LATENCY_MS}ms exceeds 5s target"
    fi
else
    log_error "Timeout waiting for database persistence"
fi

log_step "3: Verify data integrity"

# Check all actions exist
ACTION_COUNT=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -tAc "SELECT COUNT(*) FROM agent_actions WHERE correlation_id::text = '$CORRELATION_ID';" 2>/dev/null || echo "0")

if [ "$ACTION_COUNT" -eq 5 ]; then
    log_success "All 5 actions found in database"
else
    log_error "Expected 5 actions, found $ACTION_COUNT"
fi

# Verify action types
EXPECTED_TYPES=("decision" "tool_call" "tool_call" "tool_call" "success")
ACTUAL_TYPES=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -tAc "SELECT action_type FROM agent_actions WHERE correlation_id::text = '$CORRELATION_ID' ORDER BY created_at;" 2>/dev/null)

i=0
while IFS= read -r actual_type; do
    if [ "$actual_type" = "${EXPECTED_TYPES[$i]}" ]; then
        log_success "Action $((i+1)): type = $actual_type"
    else
        log_error "Action $((i+1)): expected ${EXPECTED_TYPES[$i]}, got $actual_type"
    fi
    i=$((i+1))
done <<< "$ACTUAL_TYPES"

# Verify action details are present
MISSING_DETAILS=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -tAc "SELECT COUNT(*) FROM agent_actions WHERE correlation_id::text = '$CORRELATION_ID' AND action_details = '{}'::jsonb;" 2>/dev/null || echo "0")

if [ "$MISSING_DETAILS" -eq 0 ]; then
    log_success "All actions have detailed metadata"
else
    log_error "$MISSING_DETAILS actions missing details"
fi

# Verify durations are correct
INCORRECT_DURATIONS=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -tAc "SELECT COUNT(*) FROM agent_actions WHERE correlation_id::text = '$CORRELATION_ID' AND (duration_ms IS NULL OR duration_ms < 0);" 2>/dev/null || echo "0")

if [ "$INCORRECT_DURATIONS" -eq 0 ]; then
    log_success "All actions have valid durations"
else
    log_error "$INCORRECT_DURATIONS actions with invalid durations"
fi

log_step "4: Verify correlation tracing"

# Check if we can trace the full execution
TRACE_QUERY="
SELECT
    action_type,
    action_name,
    duration_ms,
    to_char(created_at, 'HH24:MI:SS.MS') as time
FROM agent_actions
WHERE correlation_id::text = '$CORRELATION_ID'
ORDER BY created_at;
"

TRACE_RESULT=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -tAc "$TRACE_QUERY" 2>/dev/null)

if [ -n "$TRACE_RESULT" ]; then
    log_success "Full execution trace available"

    log_info "Execution timeline:"
    echo "$TRACE_RESULT" | while IFS='|' read -r action_type action_name duration time; do
        echo -e "  ${BLUE}→${NC} $time | $action_type | $action_name (${duration}ms)"
    done
else
    log_error "Cannot retrieve execution trace"
fi

log_step "5: Test idempotency"

log_info "Testing duplicate event handling..."

# Republish one action
python3 "$PROJECT_ROOT/skills/agent-tracking/log-agent-action/execute_kafka.py" \
    --agent "test-agent-e2e" \
    --action-type "decision" \
    --action-name "analyze_request" \
    --correlation-id "$CORRELATION_ID" \
    --details "{\"request\":\"test execution\",\"complexity\":\"low\"}" \
    --duration-ms 150 \
    --debug-mode &> /dev/null

sleep 2  # Wait for consumer

# Count should still be 5
FINAL_COUNT=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -tAc "SELECT COUNT(*) FROM agent_actions WHERE correlation_id::text = '$CORRELATION_ID';" 2>/dev/null || echo "0")

if [ "$FINAL_COUNT" -eq 5 ]; then
    log_success "Duplicate correctly ignored (count still 5)"
else
    log_warning "Duplicate handling issue (count=$FINAL_COUNT, expected=5)"
fi

# Summary
section_header "TEST SUMMARY"

echo ""
if [ "$TEST_FAILED" = false ]; then
    echo -e "${GREEN}╔════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║  ✅ TEST PASSED                            ║${NC}"
    echo -e "${GREEN}║  All checks successful!                   ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════╝${NC}"
    EXIT_CODE=0
else
    echo -e "${RED}╔════════════════════════════════════════════╗${NC}"
    echo -e "${RED}║  ❌ TEST FAILED                            ║${NC}"
    echo -e "${RED}║  See errors above                         ║${NC}"
    echo -e "${RED}╚════════════════════════════════════════════╝${NC}"
    EXIT_CODE=1
fi
echo ""

echo "Test Results:"
echo "  Correlation ID: $CORRELATION_ID"
echo "  Actions Logged: 5"
echo "  Actions Persisted: $ACTION_COUNT"
echo "  E2E Latency: ${LATENCY_MS}ms"
echo "  Data Integrity: $([ "$TEST_FAILED" = false ] && echo "✅ Valid" || echo "❌ Issues Found")"
echo ""

echo "Completed: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

if [ "$TEST_FAILED" = true ]; then
    echo -e "${CYAN}Troubleshooting:${NC}"
    echo "  • Check consumer logs: docker logs archon-kafka-consumer"
    echo "  • Verify Kafka connectivity: ./scripts/validate-kafka-setup.sh"
    echo "  • Run diagnostics: ./scripts/observability/diagnose_agent_logging.sh"
    echo "  • Check data: ./scripts/observability/query_agent_history.sh --correlation-id $CORRELATION_ID"
    echo ""
fi

exit $EXIT_CODE
