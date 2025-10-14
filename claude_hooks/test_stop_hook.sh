#!/bin/bash
# Comprehensive test suite for Stop hook

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOKS_LIB="${SCRIPT_DIR}/lib"

echo "======================================"
echo "Stop Hook Comprehensive Test Suite"
echo "======================================"
echo ""

# Test 1: Simple response completion
echo "Test 1: Simple response completion with tools"
echo '{"session_id": "test-001", "completion_status": "complete", "tools_executed": ["Write"]}' | \
    ${SCRIPT_DIR}/stop.sh > /dev/null
echo "✓ Test 1 passed"
echo ""

# Test 2: Multi-tool workflow
echo "Test 2: Multi-tool workflow (Read → Edit → Bash)"
echo '{"session_id": "test-002", "completion_status": "complete", "tools_executed": ["Read", "Edit", "Bash"]}' | \
    ${SCRIPT_DIR}/stop.sh > /dev/null
echo "✓ Test 2 passed"
echo ""

# Test 3: Interrupted response
echo "Test 3: Interrupted response"
echo '{"session_id": "test-003", "completion_status": "interrupted", "tools_executed": ["Write", "Edit"]}' | \
    ${SCRIPT_DIR}/stop.sh > /dev/null
echo "✓ Test 3 passed"
echo ""

# Test 4: Response without tools in JSON (database query)
echo "Test 4: Response without tools in JSON"
echo '{"session_id": "test-004", "completion_status": "complete"}' | \
    ${SCRIPT_DIR}/stop.sh > /dev/null
echo "✓ Test 4 passed"
echo ""

# Test 5: With correlation ID set
echo "Test 5: Response with correlation context"
python3 -c "
import sys
sys.path.insert(0, '${HOOKS_LIB}')
from correlation_manager import set_correlation_id
import uuid

corr_id = str(uuid.uuid4())
set_correlation_id(
    correlation_id=corr_id,
    agent_name='agent-test-suite',
    agent_domain='testing',
    prompt_preview='Test correlation linking'
)
" 2>/dev/null

echo '{"session_id": "test-005", "completion_status": "complete", "tools_executed": ["Read", "Write", "Bash"]}' | \
    ${SCRIPT_DIR}/stop.sh > /dev/null
echo "✓ Test 5 passed"
echo ""

# Test 6: Error status
echo "Test 6: Response with error status"
echo '{"session_id": "test-006", "completion_status": "error", "tools_executed": ["Write"]}' | \
    ${SCRIPT_DIR}/stop.sh > /dev/null
echo "✓ Test 6 passed"
echo ""

# Verify database entries
echo "======================================"
echo "Database Verification"
echo "======================================"
echo ""

PGPASSWORD="omninode-bridge-postgres-dev-2024" psql -h localhost -p 5436 -U postgres -d omninode_bridge -c "
SELECT
    metadata->>'session_id' as session,
    payload->>'completion_status' as status,
    payload->>'total_tools' as tools,
    metadata->>'correlation_id' IS NOT NULL as has_correlation
FROM hook_events
WHERE source = 'Stop'
AND metadata->>'session_id' LIKE 'test-%'
ORDER BY created_at DESC
LIMIT 6;
"

echo ""
echo "======================================"
echo "Performance Summary"
echo "======================================"
echo ""

# Check execution times from logs
LAST_6_TIMES=$(grep "Stop hook completed in" ${SCRIPT_DIR}/logs/stop.log | tail -6)
echo "$LAST_6_TIMES"

echo ""
echo "======================================"
echo "✅ All tests passed!"
echo "======================================"
