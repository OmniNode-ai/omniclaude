#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Test script for tool execution logging
# Verifies PostToolUse hook publishes events to Kafka and persists to agent_actions table

set -euo pipefail

# Detect project root dynamically
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== Tool Execution Logging Test ==="
echo ""

# Configuration
CORRELATION_ID=$(uuidgen)
AGENT_NAME="test-agent"
HOOK_SCRIPT="$PROJECT_ROOT/claude_hooks/post-tool-use-quality.sh"
LOG_FILE="$PROJECT_ROOT/claude_hooks/logs/post-tool-use.log"

echo "Test Configuration:"
echo "  Correlation ID: $CORRELATION_ID"
echo "  Agent Name: $AGENT_NAME"
echo "  Hook Script: $HOOK_SCRIPT"
echo ""

# Setup correlation context
export CORRELATION_ID="$CORRELATION_ID"
export AGENT_NAME="$AGENT_NAME"
export PROJECT_PATH="$PROJECT_ROOT"
export PROJECT_NAME="$(basename "$PROJECT_ROOT")"

# Create test tool info JSON (simulating a Read tool call)
TEST_TOOL_INFO=$(cat <<EOF
{
  "tool_name": "Read",
  "tool_input": {
    "file_path": "$PROJECT_ROOT/test_file.txt"
  },
  "tool_response": {
    "content": "test content",
    "lines": 10
  },
  "execution_time_ms": 150
}
EOF
)

echo "Step 1: Writing correlation context..."
python3 -c "
import sys
sys.path.insert(0, '$PROJECT_ROOT/claude_hooks/lib')
from correlation_manager import set_correlation_id

set_correlation_id(
    correlation_id='$CORRELATION_ID',
    agent_name='$AGENT_NAME',
    agent_domain='testing',
    prompt_preview='Test tool execution logging'
)
print('✓ Correlation context set')
"

echo ""
echo "Step 2: Triggering PostToolUse hook..."
echo "$TEST_TOOL_INFO" | bash "$HOOK_SCRIPT" > /dev/null
echo "✓ Hook executed"

echo ""
echo "Step 3: Waiting for async processing (2 seconds)..."
sleep 2

echo ""
echo "Step 4: Checking log file for Kafka publishing confirmation..."
if grep -q "Published tool_call event to Kafka.*correlation: $CORRELATION_ID" "$LOG_FILE" 2>/dev/null; then
    echo "✓ Kafka publishing confirmed in logs"
else
    echo "✗ No Kafka publishing confirmation found in logs"
    echo "  Recent log entries:"
    tail -n 20 "$LOG_FILE" 2>/dev/null || echo "  (log file not found)"
fi

echo ""
echo "Step 5: Waiting for Kafka consumer processing (3 seconds)..."
sleep 3

echo ""
echo "Step 6: Querying agent_actions table for test event..."

# Source .env for PostgreSQL credentials
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    source "$PROJECT_ROOT/.env"
fi

QUERY_RESULT=$(PGPASSWORD="${POSTGRES_PASSWORD}" psql -h <your-infrastructure-host> -p 5436 -U postgres -d omninode_bridge -t -c "
SELECT
    action_id,
    agent_name,
    action_type,
    action_name,
    duration_ms,
    created_at
FROM agent_actions
WHERE correlation_id = '$CORRELATION_ID'
ORDER BY created_at DESC
LIMIT 1;
" 2>&1)

if echo "$QUERY_RESULT" | grep -q "$AGENT_NAME"; then
    echo "✓ Event found in agent_actions table:"
    echo "$QUERY_RESULT"
else
    echo "✗ Event not found in agent_actions table"
    echo "  Query result:"
    echo "$QUERY_RESULT"
    echo ""
    echo "  Recent agent_actions entries:"
    PGPASSWORD="${POSTGRES_PASSWORD}" psql -h <your-infrastructure-host> -p 5436 -U postgres -d omninode_bridge -c "
    SELECT
        action_id,
        agent_name,
        action_type,
        action_name,
        correlation_id,
        created_at
    FROM agent_actions
    ORDER BY created_at DESC
    LIMIT 5;
    " 2>&1 || echo "  (database query failed)"
fi

echo ""
echo "=== Test Complete ==="
echo ""
echo "Summary:"
echo "  1. Correlation context: ✓"
echo "  2. Hook execution: ✓"
echo "  3. Kafka publishing: Check log above"
echo "  4. Database persistence: Check query above"
echo ""
echo "To verify manually:"
echo "  1. Check logs: tail -f $LOG_FILE"
echo "  2. Check Kafka topic: kcat -C -b <kafka-bootstrap-servers>:29102 -t agent-actions -o end"
echo "  3. Check database: psql -h <your-infrastructure-host> -p 5436 -U postgres -d omninode_bridge -c \"SELECT * FROM agent_actions WHERE correlation_id = '$CORRELATION_ID';\""
