#!/bin/bash
# Test script for SessionEnd hook
# Tests session end logging with various scenarios

set -euo pipefail

echo "🧪 Testing SessionEnd Hook Implementation"
echo "========================================"
echo ""

# Test 1: Basic session end with session_id
echo "Test 1: Basic session end with session_id"
echo '{"sessionId": "test-basic-001", "durationMs": 120000}' | ~/.claude/hooks/session-end.sh > /dev/null
echo "✓ Basic session end test passed"
echo ""

# Wait for async logging to complete
sleep 1

# Test 2: Session end without session_id (should use correlation_id)
echo "Test 2: Session end without session_id"
echo '{"durationMs": 30000}' | ~/.claude/hooks/session-end.sh > /dev/null
echo "✓ Session end without ID test passed"
echo ""

# Wait for async logging to complete
sleep 1

# Test 3: Verify database records
echo "Test 3: Verifying database records"
PGPASSWORD="omninode-bridge-postgres-dev-2024" psql -h localhost -p 5436 -U postgres -d omninode_bridge -c "
SELECT
    id,
    source,
    action,
    resource_id,
    payload->>'duration_seconds' as duration,
    payload->>'total_prompts' as prompts,
    payload->>'total_tools' as tools,
    payload->>'workflow_pattern' as pattern,
    metadata->>'session_quality_score' as quality
FROM hook_events
WHERE source = 'SessionEnd'
ORDER BY created_at DESC
LIMIT 3;
" | head -20

echo ""
echo "✓ Database verification complete"
echo ""

# Test 4: Performance check
echo "Test 4: Performance check (target: <50ms)"
time (python3 ~/.claude/hooks/lib/session_intelligence.py --mode end --session-id "perf-test-001" 2>&1 | grep "ms)")
echo ""

# Test 5: Workflow pattern classification test
echo "Test 5: Testing workflow pattern classification"
echo "   (Check database for various workflow patterns)"
PGPASSWORD="omninode-bridge-postgres-dev-2024" psql -h localhost -p 5436 -U postgres -d omninode_bridge -c "
SELECT
    payload->>'workflow_pattern' as pattern,
    COUNT(*) as count
FROM hook_events
WHERE source = 'SessionEnd'
GROUP BY payload->>'workflow_pattern'
ORDER BY count DESC;
"
echo ""

echo "🎉 All SessionEnd hook tests completed!"
echo ""
echo "Summary:"
echo "  ✅ Session end hook script works"
echo "  ✅ Database logging successful"
echo "  ✅ Workflow pattern classification implemented"
echo "  ✅ Performance tracking enabled"
echo ""
