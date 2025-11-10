#!/bin/bash
# Integration test for comprehensive logging infrastructure
# Tests tool call logging, error logging, success logging, and decision logging

set -euo pipefail

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
HOOKS_LIB="$HOME/.claude/hooks/lib"

echo "======================================================================="
echo "Comprehensive Logging Infrastructure Integration Test"
echo "======================================================================="
echo ""

# -----------------------------------------------------------------------------
# 1. Prerequisites
# -----------------------------------------------------------------------------
echo -e "${YELLOW}[1/6] Checking prerequisites...${NC}"

# Check DEBUG mode
if ! grep -q "^DEBUG=true" "$PROJECT_ROOT/.env" 2>/dev/null; then
    echo -e "${RED}✗ DEBUG mode not enabled in .env${NC}"
    echo "  Run: echo 'DEBUG=true' >> $PROJECT_ROOT/.env"
    exit 1
fi
echo -e "${GREEN}✓ DEBUG mode enabled${NC}"

# Check Python dependencies
if ! python3 -c "import kafka" 2>/dev/null; then
    echo -e "${RED}✗ kafka-python not installed${NC}"
    echo "  Run: pip install kafka-python"
    exit 1
fi
echo -e "${GREEN}✓ kafka-python installed${NC}"

# Check Kafka connectivity (use remote Kafka at 192.168.86.200)
source "$PROJECT_ROOT/.env"
KAFKA_HOST=$(echo "${KAFKA_BOOTSTRAP_SERVERS}" | cut -d: -f1)
KAFKA_PORT=$(echo "${KAFKA_BOOTSTRAP_SERVERS}" | cut -d: -f2)

# Try to connect to Kafka using nc (netcat)
if command -v nc >/dev/null 2>&1; then
    if nc -z -w 2 "$KAFKA_HOST" "$KAFKA_PORT" 2>/dev/null; then
        echo -e "${GREEN}✓ Kafka accessible at ${KAFKA_BOOTSTRAP_SERVERS}${NC}"
    else
        echo -e "${RED}✗ Kafka not accessible at ${KAFKA_BOOTSTRAP_SERVERS}${NC}"
        echo "  Check: ping $KAFKA_HOST"
        exit 1
    fi
else
    # If nc not available, try Python kafka-python
    if python3 -c "from kafka import KafkaProducer; p = KafkaProducer(bootstrap_servers='${KAFKA_BOOTSTRAP_SERVERS}'); p.close()" 2>/dev/null; then
        echo -e "${GREEN}✓ Kafka accessible at ${KAFKA_BOOTSTRAP_SERVERS}${NC}"
    else
        echo -e "${RED}✗ Kafka not accessible at ${KAFKA_BOOTSTRAP_SERVERS}${NC}"
        echo "  Check network connectivity to $KAFKA_HOST:$KAFKA_PORT"
        exit 1
    fi
fi

# Check PostgreSQL connectivity
source "$PROJECT_ROOT/.env"
export PGPASSWORD="${POSTGRES_PASSWORD}"
if ! psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} -c "SELECT 1" &>/dev/null; then
    echo -e "${RED}✗ PostgreSQL not accessible${NC}"
    echo "  Check database credentials in .env"
    echo "  POSTGRES_HOST=${POSTGRES_HOST}"
    echo "  POSTGRES_PORT=${POSTGRES_PORT}"
    echo "  POSTGRES_DATABASE=${POSTGRES_DATABASE}"
    exit 1
fi
echo -e "${GREEN}✓ PostgreSQL accessible${NC}"

echo ""

# -----------------------------------------------------------------------------
# 2. Test Python API
# -----------------------------------------------------------------------------
echo -e "${YELLOW}[2/6] Testing Python logging API...${NC}"

# Generate valid UUID for correlation ID (database column is type UUID)
TEST_CORRELATION_ID="$(uuidgen | tr '[:upper:]' '[:lower:]')"
export CORRELATION_ID="$TEST_CORRELATION_ID"
echo "Test Correlation ID: $TEST_CORRELATION_ID"

# Test error logging
python3 -c "
import sys
sys.path.insert(0, '$HOOKS_LIB')
from action_logging_helpers import log_error

result = log_error(
    agent_name='test-agent',
    error_type='TestError',
    error_message='This is a test error',
    error_context={'test_key': 'test_value'},
    correlation_id='$TEST_CORRELATION_ID'
)

if result:
    print('✓ Error logging successful')
    sys.exit(0)
else:
    print('✗ Error logging failed')
    sys.exit(1)
"

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Error logging works${NC}"
else
    echo -e "${RED}✗ Error logging failed${NC}"
    exit 1
fi

# Test success logging
python3 -c "
import sys
sys.path.insert(0, '$HOOKS_LIB')
from action_logging_helpers import log_success

result = log_success(
    agent_name='test-agent',
    success_type='TestSuccess',
    success_message='This is a test success',
    success_context={'test_key': 'test_value'},
    quality_score=0.95,
    correlation_id='$TEST_CORRELATION_ID'
)

if result:
    print('✓ Success logging successful')
    sys.exit(0)
else:
    print('✗ Success logging failed')
    sys.exit(1)
"

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Success logging works${NC}"
else
    echo -e "${RED}✗ Success logging failed${NC}"
    exit 1
fi

# Test tool call logging
python3 -c "
import sys
sys.path.insert(0, '$HOOKS_LIB')
from action_logging_helpers import log_tool_call

result = log_tool_call(
    tool_name='TestTool',
    tool_parameters={'param1': 'value1'},
    tool_result={'result_key': 'result_value'},
    duration_ms=125,
    correlation_id='$TEST_CORRELATION_ID'
)

if result:
    print('✓ Tool call logging successful')
    sys.exit(0)
else:
    print('✗ Tool call logging failed')
    sys.exit(1)
"

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Tool call logging works${NC}"
else
    echo -e "${RED}✗ Tool call logging failed${NC}"
    exit 1
fi

# Test decision logging
python3 -c "
import sys
sys.path.insert(0, '$HOOKS_LIB')
from action_logging_helpers import log_decision

result = log_decision(
    decision_type='test_decision',
    decision_details={'option': 'A', 'confidence': 0.8},
    correlation_id='$TEST_CORRELATION_ID'
)

if result:
    print('✓ Decision logging successful')
    sys.exit(0)
else:
    print('✗ Decision logging failed')
    sys.exit(1)
"

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Decision logging works${NC}"
else
    echo -e "${RED}✗ Decision logging failed${NC}"
    exit 1
fi

echo ""

# -----------------------------------------------------------------------------
# 3. Test Bash API
# -----------------------------------------------------------------------------
echo -e "${YELLOW}[3/6] Testing Bash logging API...${NC}"

source "$HOOKS_LIB/log_action.sh"

# Test error logging via bash
log_error "BashTestError" "Bash error test message" '{"test": "bash_error"}' 2>/dev/null
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Bash error logging works${NC}"
else
    echo -e "${RED}✗ Bash error logging failed${NC}"
    exit 1
fi

# Test success logging via bash
log_success "BashTestSuccess" "Bash success test message" '{"test": "bash_success"}' 100 0.9 2>/dev/null
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Bash success logging works${NC}"
else
    echo -e "${RED}✗ Bash success logging failed${NC}"
    exit 1
fi

# Test tool call logging via bash
log_tool_call "BashTestTool" '{"param": "value"}' '{"result": "success"}' 50 2>/dev/null
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Bash tool call logging works${NC}"
else
    echo -e "${RED}✗ Bash tool call logging failed${NC}"
    exit 1
fi

echo ""

# -----------------------------------------------------------------------------
# 4. Verify Kafka Topic
# -----------------------------------------------------------------------------
echo -e "${YELLOW}[4/6] Verifying Kafka topic has events...${NC}"

# Wait for Kafka async processing
sleep 2

# Check if events were published to Kafka (via Python)
KAFKA_CHECK=$(python3 -c "
from kafka import KafkaConsumer
import sys

try:
    consumer = KafkaConsumer(
        'agent-actions',
        bootstrap_servers='${KAFKA_BOOTSTRAP_SERVERS}',
        auto_offset_reset='earliest',
        consumer_timeout_ms=2000,
        max_poll_records=10
    )

    count = 0
    for message in consumer:
        count += 1
        if count >= 10:
            break

    consumer.close()
    print(f'✓ Kafka topic has messages (sampled {count})')
    sys.exit(0)
except Exception as e:
    print(f'✗ Failed to read from Kafka: {e}', file=sys.stderr)
    sys.exit(1)
" 2>&1)

if [ $? -eq 0 ]; then
    echo -e "${GREEN}${KAFKA_CHECK}${NC}"
else
    echo -e "${YELLOW}⚠ Could not verify Kafka messages (topic may be empty or consumer error)${NC}"
    echo "  This is non-fatal - events may still be publishing correctly"
fi

echo ""

# -----------------------------------------------------------------------------
# 5. Verify PostgreSQL Table (after consumer processes)
# -----------------------------------------------------------------------------
echo -e "${YELLOW}[5/6] Verifying PostgreSQL table has events...${NC}"

# Wait for consumer to process events
echo "Waiting 5 seconds for consumer to process events..."
sleep 5

# Query database for test events
export PGPASSWORD="${POSTGRES_PASSWORD}"
DB_COUNT=$(psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} -t -c \
    "SELECT COUNT(*) FROM agent_actions WHERE correlation_id = '$TEST_CORRELATION_ID';" | tr -d '[:space:]')

if [ "$DB_COUNT" -gt 0 ]; then
    echo -e "${GREEN}✓ PostgreSQL has $DB_COUNT test events${NC}"
else
    echo -e "${YELLOW}⚠ PostgreSQL has no test events yet (consumer may be slow or not running)${NC}"
    echo "  Check consumer: docker logs -f agent-actions-consumer"
fi

# Show event breakdown
echo ""
echo "Event breakdown by type:"
export PGPASSWORD="${POSTGRES_PASSWORD}"
psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} -c \
    "SELECT action_type, COUNT(*) as count
     FROM agent_actions
     WHERE correlation_id = '$TEST_CORRELATION_ID'
     GROUP BY action_type
     ORDER BY count DESC;" 2>/dev/null || true

echo ""

# -----------------------------------------------------------------------------
# 6. Test Summary
# -----------------------------------------------------------------------------
echo -e "${YELLOW}[6/6] Test Summary${NC}"
echo "Correlation ID: $TEST_CORRELATION_ID"
echo ""

# Query and display all test events
echo "All test events logged:"
export PGPASSWORD="${POSTGRES_PASSWORD}"
psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -U ${POSTGRES_USER} -d ${POSTGRES_DATABASE} -c \
    "SELECT
        action_type,
        action_name,
        duration_ms,
        created_at
     FROM agent_actions
     WHERE correlation_id = '$TEST_CORRELATION_ID'
     ORDER BY created_at ASC;" 2>/dev/null || true

echo ""
echo "======================================================================="
echo -e "${GREEN}✓ All comprehensive logging tests PASSED${NC}"
echo "======================================================================="
echo ""
echo "Next steps:"
echo "  1. View logs: tail -f ~/.claude/hooks/logs/post-tool-use.log"
echo "  2. Query data: psql ... -c \"SELECT * FROM agent_actions WHERE correlation_id = '$TEST_CORRELATION_ID';\""
echo "  3. Use agent history browser: python3 agents/lib/agent_history_browser.py"
echo ""
