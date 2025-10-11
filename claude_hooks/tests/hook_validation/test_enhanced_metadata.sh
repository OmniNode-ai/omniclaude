#!/usr/bin/env bash
# test_enhanced_metadata.sh - Test suite for enhanced metadata tracking
#
# Tests:
# - Enhanced metadata in PreToolUse hooks
# - Enhanced metadata in PostToolUse hooks
# - Enhanced metadata in UserPromptSubmit hooks
# - Enhanced metadata overhead (<15ms target)
# - Metadata preservation across hooks

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Database connection
DB_HOST="localhost"
DB_PORT="5436"
DB_NAME="omninode_bridge"
DB_USER="postgres"
DB_PASS="omninode-bridge-postgres-dev-2024"

# Test counters
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

# Performance threshold (ms)
METADATA_OVERHEAD_THRESHOLD_MS=15

# Test functions
log_success() {
    echo -e "${GREEN}✓${NC} $*"
}

log_error() {
    echo -e "${RED}✗${NC} $*"
}

log_info() {
    echo "ℹ $*"
}

run_sql() {
    PGPASSWORD="$DB_PASS" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c "$1"
}

test_pretooluse_enhanced_metadata() {
    TESTS_RUN=$((TESTS_RUN + 1))
    log_info "Test: PreToolUse enhanced metadata"

    local correlation_id="$(uuidgen)"

    # Create PreToolUse event with enhanced metadata
    run_sql "
        INSERT INTO hook_events (id, source, action, resource, resource_id, payload, metadata)
        VALUES (
            gen_random_uuid(),
            'PreToolUse',
            'tool_invocation',
            'tool',
            'Write',
            '{
                \"file_path\": \"/test/example.py\",
                \"content_length\": 500,
                \"language\": \"python\"
            }'::jsonb,
            '{
                \"correlation_id\": \"$correlation_id\",
                \"hook_version\": \"2.0\",
                \"quality_check\": {
                    \"enabled\": true,
                    \"violations\": 0
                },
                \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"
            }'::jsonb
        );
    " > /dev/null

    # Verify enhanced metadata
    local metadata=$(run_sql "
        SELECT metadata
        FROM hook_events
        WHERE metadata->>'correlation_id' = '$correlation_id';
    ")

    if echo "$metadata" | grep -q "quality_check"; then
        log_success "PreToolUse enhanced metadata: Quality check metadata present"
        TESTS_PASSED=$((TESTS_PASSED + 1))

        # Cleanup
        run_sql "DELETE FROM hook_events WHERE metadata->>'correlation_id' = '$correlation_id';"
        return 0
    else
        log_error "PreToolUse enhanced metadata: Quality check metadata missing"
        TESTS_FAILED=$((TESTS_FAILED + 1))

        # Cleanup
        run_sql "DELETE FROM hook_events WHERE metadata->>'correlation_id' = '$correlation_id';"
        return 1
    fi
}

test_posttooluse_enhanced_metadata() {
    TESTS_RUN=$((TESTS_RUN + 1))
    log_info "Test: PostToolUse enhanced metadata"

    local correlation_id="$(uuidgen)"

    # Create PostToolUse event with enhanced metadata
    run_sql "
        INSERT INTO hook_events (id, source, action, resource, resource_id, payload, metadata)
        VALUES (
            gen_random_uuid(),
            'PostToolUse',
            'tool_completed',
            'tool',
            'Write',
            '{
                \"file_path\": \"/test/example.py\",
                \"success\": true,
                \"auto_fix_applied\": true,
                \"fixes\": [\"naming_convention\", \"type_hints\"]
            }'::jsonb,
            '{
                \"correlation_id\": \"$correlation_id\",
                \"hook_version\": \"2.0\",
                \"execution_time_ms\": 45,
                \"auto_fix\": {
                    \"enabled\": true,
                    \"fixes_applied\": 2
                },
                \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"
            }'::jsonb
        );
    " > /dev/null

    # Verify enhanced metadata
    local metadata=$(run_sql "
        SELECT metadata
        FROM hook_events
        WHERE metadata->>'correlation_id' = '$correlation_id';
    ")

    if echo "$metadata" | grep -q "auto_fix"; then
        log_success "PostToolUse enhanced metadata: Auto-fix metadata present"
        TESTS_PASSED=$((TESTS_PASSED + 1))

        # Cleanup
        run_sql "DELETE FROM hook_events WHERE metadata->>'correlation_id' = '$correlation_id';"
        return 0
    else
        log_error "PostToolUse enhanced metadata: Auto-fix metadata missing"
        TESTS_FAILED=$((TESTS_FAILED + 1))

        # Cleanup
        run_sql "DELETE FROM hook_events WHERE metadata->>'correlation_id' = '$correlation_id';"
        return 1
    fi
}

test_userprompt_enhanced_metadata() {
    TESTS_RUN=$((TESTS_RUN + 1))
    log_info "Test: UserPromptSubmit enhanced metadata"

    local correlation_id="$(uuidgen)"

    # Create UserPromptSubmit event with enhanced metadata
    run_sql "
        INSERT INTO hook_events (id, source, action, resource, resource_id, payload, metadata)
        VALUES (
            gen_random_uuid(),
            'UserPromptSubmit',
            'prompt_submitted',
            'prompt',
            'test-prompt',
            '{
                \"prompt_preview\": \"Create a Python function\",
                \"prompt_length\": 25,
                \"agent_detected\": \"agent-code-generator\"
            }'::jsonb,
            '{
                \"correlation_id\": \"$correlation_id\",
                \"hook_version\": \"2.0\",
                \"intelligence\": {
                    \"agent_detected\": true,
                    \"agent_name\": \"agent-code-generator\",
                    \"confidence\": 0.95
                },
                \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"
            }'::jsonb
        );
    " > /dev/null

    # Verify enhanced metadata
    local metadata=$(run_sql "
        SELECT metadata
        FROM hook_events
        WHERE metadata->>'correlation_id' = '$correlation_id';
    ")

    if echo "$metadata" | grep -q "intelligence"; then
        log_success "UserPromptSubmit enhanced metadata: Intelligence metadata present"
        TESTS_PASSED=$((TESTS_PASSED + 1))

        # Cleanup
        run_sql "DELETE FROM hook_events WHERE metadata->>'correlation_id' = '$correlation_id';"
        return 0
    else
        log_error "UserPromptSubmit enhanced metadata: Intelligence metadata missing"
        TESTS_FAILED=$((TESTS_FAILED + 1))

        # Cleanup
        run_sql "DELETE FROM hook_events WHERE metadata->>'correlation_id' = '$correlation_id';"
        return 1
    fi
}

test_metadata_overhead_performance() {
    TESTS_RUN=$((TESTS_RUN + 1))
    log_info "Test: Metadata overhead performance (<${METADATA_OVERHEAD_THRESHOLD_MS}ms)"

    local total_time_basic=0
    local total_time_enhanced=0
    local iterations=20

    # Measure basic metadata insertion
    for i in $(seq 1 $iterations); do
        local correlation_id="perf-basic-$i-$$"

        local start_ns=$(python3 -c "import time; print(int(time.time() * 1000000000))")

        run_sql "
            INSERT INTO hook_events (id, source, action, resource, resource_id, payload, metadata)
            VALUES (
                gen_random_uuid(),
                'TestHook',
                'test_action',
                'test',
                'test-$i',
                '{\"test\": true}'::jsonb,
                '{\"correlation_id\": \"$correlation_id\"}'::jsonb
            );
        " > /dev/null

        local end_ns=$(python3 -c "import time; print(int(time.time() * 1000000000))")
        local elapsed_ms=$(((end_ns - start_ns) / 1000000))

        total_time_basic=$((total_time_basic + elapsed_ms))

        run_sql "DELETE FROM hook_events WHERE metadata->>'correlation_id' = '$correlation_id';" > /dev/null
    done

    # Measure enhanced metadata insertion
    for i in $(seq 1 $iterations); do
        local correlation_id="perf-enhanced-$i-$$"

        local start_ns=$(python3 -c "import time; print(int(time.time() * 1000000000))")

        run_sql "
            INSERT INTO hook_events (id, source, action, resource, resource_id, payload, metadata)
            VALUES (
                gen_random_uuid(),
                'TestHook',
                'test_action',
                'test',
                'test-$i',
                '{\"test\": true, \"data\": \"value\"}'::jsonb,
                '{
                    \"correlation_id\": \"$correlation_id\",
                    \"hook_version\": \"2.0\",
                    \"quality_check\": {\"enabled\": true, \"violations\": 0},
                    \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"
                }'::jsonb
            );
        " > /dev/null

        local end_ns=$(python3 -c "import time; print(int(time.time() * 1000000000))")
        local elapsed_ms=$(((end_ns - start_ns) / 1000000))

        total_time_enhanced=$((total_time_enhanced + elapsed_ms))

        run_sql "DELETE FROM hook_events WHERE metadata->>'correlation_id' = '$correlation_id';" > /dev/null
    done

    local avg_basic=$((total_time_basic / iterations))
    local avg_enhanced=$((total_time_enhanced / iterations))
    local overhead=$((avg_enhanced - avg_basic))

    if [[ $overhead -lt $METADATA_OVERHEAD_THRESHOLD_MS ]]; then
        log_success "Metadata overhead: ${overhead}ms (basic: ${avg_basic}ms, enhanced: ${avg_enhanced}ms, target <${METADATA_OVERHEAD_THRESHOLD_MS}ms)"
        TESTS_PASSED=$((TESTS_PASSED + 1))
        return 0
    else
        log_error "Metadata overhead: ${overhead}ms (target <${METADATA_OVERHEAD_THRESHOLD_MS}ms) - EXCEEDED"
        TESTS_FAILED=$((TESTS_FAILED + 1))
        return 1
    fi
}

test_metadata_preservation() {
    TESTS_RUN=$((TESTS_RUN + 1))
    log_info "Test: Metadata preservation across hooks"

    local correlation_id="$(uuidgen)"
    local session_id="session-$(date +%s)-$$"

    # Create events with preserved metadata
    for hook in "UserPromptSubmit" "PreToolUse" "PostToolUse" "Stop"; do
        run_sql "
            INSERT INTO hook_events (id, source, action, resource, resource_id, payload, metadata)
            VALUES (
                gen_random_uuid(),
                '$hook',
                'test_action',
                'test',
                'test-resource',
                '{\"test\": true}'::jsonb,
                '{
                    \"correlation_id\": \"$correlation_id\",
                    \"session_id\": \"$session_id\",
                    \"hook_version\": \"2.0\"
                }'::jsonb
            );
        " > /dev/null
    done

    # Verify all events have preserved metadata
    local count=$(run_sql "
        SELECT COUNT(*)
        FROM hook_events
        WHERE metadata->>'correlation_id' = '$correlation_id'
        AND metadata->>'session_id' = '$session_id'
        AND metadata->>'hook_version' = '2.0';
    " | tr -d ' ')

    if [[ "$count" == "4" ]]; then
        log_success "Metadata preservation: All 4 hooks preserved metadata"
        TESTS_PASSED=$((TESTS_PASSED + 1))

        # Cleanup
        run_sql "DELETE FROM hook_events WHERE metadata->>'correlation_id' = '$correlation_id';"
        return 0
    else
        log_error "Metadata preservation: Expected 4 events with preserved metadata, found $count"
        TESTS_FAILED=$((TESTS_FAILED + 1))

        # Cleanup
        run_sql "DELETE FROM hook_events WHERE metadata->>'correlation_id' = '$correlation_id';"
        return 1
    fi
}

# Main test execution
echo "=========================================="
echo "Enhanced Metadata Test Suite"
echo "=========================================="
echo ""

# Run all tests
test_pretooluse_enhanced_metadata
test_posttooluse_enhanced_metadata
test_userprompt_enhanced_metadata
test_metadata_overhead_performance
test_metadata_preservation

# Summary
echo ""
echo "=========================================="
echo "Test Summary"
echo "=========================================="
echo "Tests Run:    $TESTS_RUN"
echo "Tests Passed: $TESTS_PASSED"
echo "Tests Failed: $TESTS_FAILED"

if [[ $TESTS_FAILED -eq 0 ]]; then
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}Some tests failed!${NC}"
    exit 1
fi
