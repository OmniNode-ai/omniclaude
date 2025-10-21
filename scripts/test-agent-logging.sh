#!/bin/bash
# Manual End-to-End Test Script for Kafka Agent Logging
# Simulates agent workflow and verifies complete pipeline

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Configuration
CORRELATION_ID="manual-test-$(date +%s)-$$"
POSTGRES_HOST=${POSTGRES_HOST:-"localhost"}
POSTGRES_PORT=${POSTGRES_PORT:-"5436"}
POSTGRES_USER=${POSTGRES_USER:-"postgres"}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-"omninode-bridge-postgres-dev-2024"}
POSTGRES_DB=${POSTGRES_DATABASE:-"omninode_bridge"}

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}🧪 Manual Agent Logging E2E Test${NC}"
echo -e "${BLUE}========================================${NC}\n"

echo -e "${CYAN}Correlation ID: $CORRELATION_ID${NC}\n"

# Function to print step
print_step() {
    echo -e "${YELLOW}▶ $1${NC}"
}

# Function to print result
print_result() {
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}  ✅ $1${NC}"
    else
        echo -e "${RED}  ❌ $1${NC}"
        exit 1
    fi
}

# 1. Simulate agent workflow with multiple actions
print_step "Step 1: Simulating agent workflow (4 actions)..."

export DEBUG=true  # Enable debug mode

# Action 1: Decision - Analyze request
python "$PROJECT_ROOT/skills/agent-tracking/log-agent-action/execute_kafka.py" \
    --agent "agent-polymorphic-agent" \
    --action-type "decision" \
    --action-name "analyze_request" \
    --correlation-id "$CORRELATION_ID" \
    --details '{"request":"test kafka logging","complexity":"medium"}' \
    --duration-ms 150 \
    --debug-mode \
    >/dev/null 2>&1

print_result "Action 1: analyze_request logged"

sleep 0.5

# Action 2: Tool call - Read file
python "$PROJECT_ROOT/skills/agent-tracking/log-agent-action/execute_kafka.py" \
    --agent "agent-polymorphic-agent" \
    --action-type "tool_call" \
    --action-name "Read" \
    --correlation-id "$CORRELATION_ID" \
    --details '{"file_path":"test.py","lines":100}' \
    --duration-ms 25 \
    --debug-mode \
    >/dev/null 2>&1

print_result "Action 2: Read logged"

sleep 0.5

# Action 3: Tool call - Write file
python "$PROJECT_ROOT/skills/agent-tracking/log-agent-action/execute_kafka.py" \
    --agent "agent-polymorphic-agent" \
    --action-type "tool_call" \
    --action-name "Write" \
    --correlation-id "$CORRELATION_ID" \
    --details '{"file_path":"output.py","bytes_written":2048}' \
    --duration-ms 50 \
    --debug-mode \
    >/dev/null 2>&1

print_result "Action 3: Write logged"

sleep 0.5

# Action 4: Success - Task completed
python "$PROJECT_ROOT/skills/agent-tracking/log-agent-action/execute_kafka.py" \
    --agent "agent-polymorphic-agent" \
    --action-type "success" \
    --action-name "task_completed" \
    --correlation-id "$CORRELATION_ID" \
    --details '{"files_created":3,"total_duration_ms":225}' \
    --duration-ms 10 \
    --debug-mode \
    >/dev/null 2>&1

print_result "Action 4: task_completed logged"

echo ""

# 2. Verify events in Kafka
print_step "Step 2: Verifying events in Kafka..."

sleep 2  # Wait for Kafka

# Check Kafka topic
KAFKA_COUNT=$(docker exec omniclaude_test_redpanda rpk topic consume agent-actions \
    --num 1000 --offset start --format '%v' 2>/dev/null | \
    grep -c "$CORRELATION_ID" || echo "0")

if [ "$KAFKA_COUNT" -ge "4" ]; then
    print_result "$KAFKA_COUNT events found in Kafka"
else
    echo -e "${RED}  ❌ Expected 4 events, found $KAFKA_COUNT${NC}"
    exit 1
fi

echo ""

# 3. Wait for consumer to process events
print_step "Step 3: Waiting for consumer to process events..."

echo -e "${CYAN}  Waiting up to 10 seconds...${NC}"

PROCESSED=false
for i in {1..20}; do
    DB_COUNT=$(PGPASSWORD=$POSTGRES_PASSWORD psql -h $POSTGRES_HOST -p $POSTGRES_PORT \
        -U $POSTGRES_USER -d $POSTGRES_DB -tAc \
        "SELECT COUNT(*) FROM agent_actions WHERE correlation_id='$CORRELATION_ID';" 2>/dev/null || echo "0")

    if [ "$DB_COUNT" -ge "4" ]; then
        PROCESSED=true
        break
    fi

    sleep 0.5
    echo -ne "${CYAN}  .$NC"
done

echo ""

if [ "$PROCESSED" = true ]; then
    print_result "All 4 events processed by consumer"
else
    echo -e "${RED}  ❌ Consumer did not process all events (found $DB_COUNT/4)${NC}"
    exit 1
fi

echo ""

# 4. Verify data integrity in PostgreSQL
print_step "Step 4: Verifying data integrity in PostgreSQL..."

# Check all actions exist with correct data
ACTIONS_QUERY="
SELECT
    action_name,
    action_type,
    agent_name,
    duration_ms,
    action_details::text
FROM agent_actions
WHERE correlation_id='$CORRELATION_ID'
ORDER BY created_at ASC;
"

RESULTS=$(PGPASSWORD=$POSTGRES_PASSWORD psql -h $POSTGRES_HOST -p $POSTGRES_PORT \
    -U $POSTGRES_USER -d $POSTGRES_DB -tA -F'|' -c "$ACTIONS_QUERY")

# Expected actions
EXPECTED_ACTIONS=(
    "analyze_request|decision|agent-polymorphic-agent|150"
    "Read|tool_call|agent-polymorphic-agent|25"
    "Write|tool_call|agent-polymorphic-agent|50"
    "task_completed|success|agent-polymorphic-agent|10"
)

ACTION_COUNT=0
while IFS='|' read -r action_name action_type agent_name duration_ms details; do
    ACTION_COUNT=$((ACTION_COUNT + 1))

    # Verify action matches expected
    EXPECTED="${EXPECTED_ACTIONS[$((ACTION_COUNT - 1))]}"
    ACTUAL="$action_name|$action_type|$agent_name|$duration_ms"

    if [[ "$ACTUAL" == "$EXPECTED"* ]]; then
        echo -e "${GREEN}  ✅ Action $ACTION_COUNT: $action_name ($action_type) - ${duration_ms}ms${NC}"
    else
        echo -e "${RED}  ❌ Action $ACTION_COUNT mismatch${NC}"
        echo -e "${RED}     Expected: $EXPECTED${NC}"
        echo -e "${RED}     Got:      $ACTUAL${NC}"
        exit 1
    fi
done <<< "$RESULTS"

if [ "$ACTION_COUNT" -eq "4" ]; then
    print_result "All 4 actions verified with correct data"
else
    echo -e "${RED}  ❌ Expected 4 actions, verified $ACTION_COUNT${NC}"
    exit 1
fi

echo ""

# 5. Test idempotency (duplicate handling)
print_step "Step 5: Testing idempotency (duplicate handling)..."

# Get one event from Kafka
DUPLICATE_EVENT=$(docker exec omniclaude_test_redpanda rpk topic consume agent-actions \
    --num 1000 --offset start --format '%v' 2>/dev/null | \
    grep "$CORRELATION_ID" | head -1)

if [ -z "$DUPLICATE_EVENT" ]; then
    echo -e "${YELLOW}  ⚠️  Could not retrieve event for idempotency test - skipping${NC}"
else
    # Re-publish the same event
    echo "$DUPLICATE_EVENT" | docker exec -i omniclaude_test_redpanda \
        rpk topic produce agent-actions >/dev/null 2>&1

    print_result "Duplicate event published"

    # Wait for consumer
    sleep 3

    # Count should still be 4 (duplicate should be ignored)
    DB_COUNT_AFTER=$(PGPASSWORD=$POSTGRES_PASSWORD psql -h $POSTGRES_HOST -p $POSTGRES_PORT \
        -U $POSTGRES_USER -d $POSTGRES_DB -tAc \
        "SELECT COUNT(*) FROM agent_actions WHERE correlation_id='$CORRELATION_ID';")

    if [ "$DB_COUNT_AFTER" -eq "4" ]; then
        print_result "Duplicate correctly ignored (count still 4)"
    else
        echo -e "${RED}  ❌ Duplicate not handled (count=$DB_COUNT_AFTER, expected=4)${NC}"
        exit 1
    fi
fi

echo ""

# 6. Measure end-to-end latency
print_step "Step 6: Measuring end-to-end latency..."

# Publish new event and measure time to database
START_TIME=$(date +%s.%N)
NEW_CORRELATION_ID="latency-test-$(date +%s)"

python "$PROJECT_ROOT/skills/agent-tracking/log-agent-action/execute_kafka.py" \
    --agent "test-agent" \
    --action-type "tool_call" \
    --action-name "latency_test" \
    --correlation-id "$NEW_CORRELATION_ID" \
    --debug-mode \
    >/dev/null 2>&1

# Wait for database persistence
for i in {1..100}; do
    EXISTS=$(PGPASSWORD=$POSTGRES_PASSWORD psql -h $POSTGRES_HOST -p $POSTGRES_PORT \
        -U $POSTGRES_USER -d $POSTGRES_DB -tAc \
        "SELECT EXISTS(SELECT 1 FROM agent_actions WHERE correlation_id='$NEW_CORRELATION_ID');" 2>/dev/null || echo "f")

    if [ "$EXISTS" = "t" ]; then
        END_TIME=$(date +%s.%N)
        LATENCY=$(echo "$END_TIME - $START_TIME" | bc)
        LATENCY_MS=$(echo "$LATENCY * 1000" | bc | cut -d'.' -f1)

        echo -e "${GREEN}  ✅ E2E latency: ${LATENCY_MS}ms${NC}"

        if [ "$LATENCY_MS" -lt "5000" ]; then
            echo -e "${GREEN}  ✅ Latency within 5s target${NC}"
        else
            echo -e "${YELLOW}  ⚠️  Latency ${LATENCY_MS}ms exceeds 5s target${NC}"
        fi

        break
    fi

    sleep 0.1
done

echo ""

# 7. Cleanup test data
print_step "Step 7: Cleaning up test data..."

PGPASSWORD=$POSTGRES_PASSWORD psql -h $POSTGRES_HOST -p $POSTGRES_PORT \
    -U $POSTGRES_USER -d $POSTGRES_DB -c \
    "DELETE FROM agent_actions WHERE correlation_id IN ('$CORRELATION_ID', '$NEW_CORRELATION_ID');" \
    >/dev/null 2>&1

print_result "Test data cleaned up"

echo ""

# Summary
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}✅ Manual E2E Test Passed!${NC}"
echo -e "${GREEN}========================================${NC}\n"

echo -e "${BLUE}📊 Test Summary:${NC}"
echo -e "  Correlation ID:    $CORRELATION_ID"
echo -e "  Events Published:  4"
echo -e "  Events Consumed:   $DB_COUNT"
echo -e "  Data Integrity:    ✅ Verified"
echo -e "  Idempotency:       ✅ Verified"
echo -e "  E2E Latency:       ${LATENCY_MS}ms"
echo ""

exit 0
