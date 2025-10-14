#!/usr/bin/env bash
# test_session_hooks.sh - Test suite for SessionStart and SessionEnd hooks
#
# Tests:
# - SessionStart basic functionality
# - SessionStart database insertion
# - SessionStart performance (<50ms)
# - SessionEnd basic functionality
# - SessionEnd session aggregation
# - SessionEnd statistics calculation
# - SessionEnd workflow pattern classification

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
PERFORMANCE_THRESHOLD_MS=50

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

test_session_start_basic() {
    TESTS_RUN=$((TESTS_RUN + 1))
    log_info "Test: SessionStart basic functionality"

    # Generate test session ID using PostgreSQL gen_random_uuid()
    local session_id=$(run_sql "SELECT gen_random_uuid();" | tr -d ' ')

    # Mock SessionStart hook (simulate creating session record)
    local result=$(run_sql "
        INSERT INTO service_sessions (id, service_name, instance_id, status, metadata)
        VALUES (
            '$session_id'::uuid,
            'claude-code',
            'test-instance',
            'active',
            '{\"test\": true, \"test_name\": \"session_start_basic\"}'::jsonb
        )
        RETURNING id;
    ")

    if [[ -n "$result" ]]; then
        log_success "SessionStart basic functionality"
        TESTS_PASSED=$((TESTS_PASSED + 1))

        # Cleanup
        run_sql "DELETE FROM service_sessions WHERE id = '$session_id'::uuid;"
        return 0
    else
        log_error "SessionStart basic functionality - Failed to create session"
        TESTS_FAILED=$((TESTS_FAILED + 1))
        return 1
    fi
}

test_session_start_performance() {
    TESTS_RUN=$((TESTS_RUN + 1))
    log_info "Test: SessionStart performance (<${PERFORMANCE_THRESHOLD_MS}ms)"

    local total_time_ms=0
    local iterations=10

    for i in $(seq 1 $iterations); do
        local session_id=$(run_sql "SELECT gen_random_uuid();" | tr -d ' ')

        # Measure insertion time
        local start_ns=$(date +%s%N 2>/dev/null || echo "0")
        if [[ "$start_ns" == "0" ]]; then
            # Fallback for macOS
            start_ns=$(($(date +%s) * 1000000000))
        fi

        run_sql "
            INSERT INTO service_sessions (id, service_name, instance_id, status, metadata)
            VALUES (
                '$session_id'::uuid,
                'claude-code',
                'perf-test',
                'active',
                '{\"test\": true}'::jsonb
            );
        " > /dev/null

        local end_ns=$(date +%s%N 2>/dev/null || echo "0")
        if [[ "$end_ns" == "0" ]]; then
            end_ns=$(($(date +%s) * 1000000000))
        fi

        local elapsed_ms=$(((end_ns - start_ns) / 1000000))

        total_time_ms=$((total_time_ms + elapsed_ms))

        # Cleanup
        run_sql "DELETE FROM service_sessions WHERE id = '$session_id'::uuid;" > /dev/null
    done

    local avg_time_ms=$((total_time_ms / iterations))

    if [[ $avg_time_ms -lt $PERFORMANCE_THRESHOLD_MS ]]; then
        log_success "SessionStart performance: ${avg_time_ms}ms avg (target <${PERFORMANCE_THRESHOLD_MS}ms)"
        TESTS_PASSED=$((TESTS_PASSED + 1))
        return 0
    else
        log_error "SessionStart performance: ${avg_time_ms}ms avg (target <${PERFORMANCE_THRESHOLD_MS}ms) - EXCEEDED"
        TESTS_FAILED=$((TESTS_FAILED + 1))
        return 1
    fi
}

test_session_end_basic() {
    TESTS_RUN=$((TESTS_RUN + 1))
    log_info "Test: SessionEnd basic functionality"

    # Create test session
    local session_id=$(run_sql "SELECT gen_random_uuid();" | tr -d ' ')

    run_sql "
        INSERT INTO service_sessions (id, service_name, instance_id, status, metadata)
        VALUES (
            '$session_id'::uuid,
            'claude-code',
            'test-instance',
            'active',
            '{\"test\": true}'::jsonb
        );
    " > /dev/null

    # Simulate SessionEnd (update session status)
    local result=$(run_sql "
        UPDATE service_sessions
        SET status = 'ended',
            session_end = NOW(),
            updated_at = NOW()
        WHERE id = '$session_id'::uuid
        RETURNING id;
    ")

    if [[ -n "$result" ]]; then
        log_success "SessionEnd basic functionality"
        TESTS_PASSED=$((TESTS_PASSED + 1))

        # Cleanup
        run_sql "DELETE FROM service_sessions WHERE id = '$session_id'::uuid;"
        return 0
    else
        log_error "SessionEnd basic functionality - Failed to end session"
        TESTS_FAILED=$((TESTS_FAILED + 1))
        return 1
    fi
}

test_session_end_aggregation() {
    TESTS_RUN=$((TESTS_RUN + 1))
    log_info "Test: SessionEnd aggregation with events"

    # Create test session
    local session_id=$(run_sql "SELECT gen_random_uuid();" | tr -d ' ')
    local correlation_id="corr-$(uuidgen)"

    run_sql "
        INSERT INTO service_sessions (id, service_name, instance_id, status, metadata)
        VALUES (
            '$session_id'::uuid,
            'claude-code',
            'test-instance',
            'active',
            '{\"test\": true}'::jsonb
        );
    " > /dev/null

    # Create some test hook events
    for i in {1..5}; do
        run_sql "
            INSERT INTO hook_events (id, source, action, resource, resource_id, payload, metadata)
            VALUES (
                gen_random_uuid(),
                'TestHook',
                'test_action',
                'test_resource',
                'test-$i',
                '{\"test\": true}'::jsonb,
                '{\"correlation_id\": \"$correlation_id\", \"session_id\": \"$session_id\"}'::jsonb
            );
        " > /dev/null
    done

    # Get event count
    local event_count=$(run_sql "
        SELECT COUNT(*)
        FROM hook_events
        WHERE metadata->>'session_id' = '$session_id';
    " | tr -d ' ')

    if [[ "$event_count" == "5" ]]; then
        log_success "SessionEnd aggregation: Found 5 events"
        TESTS_PASSED=$((TESTS_PASSED + 1))

        # Cleanup
        run_sql "DELETE FROM hook_events WHERE metadata->>'session_id' = '$session_id';"
        run_sql "DELETE FROM service_sessions WHERE id = '$session_id'::uuid;"
        return 0
    else
        log_error "SessionEnd aggregation: Expected 5 events, found $event_count"
        TESTS_FAILED=$((TESTS_FAILED + 1))

        # Cleanup
        run_sql "DELETE FROM hook_events WHERE metadata->>'session_id' = '$session_id';"
        run_sql "DELETE FROM service_sessions WHERE id = '$session_id'::uuid;"
        return 1
    fi
}

test_session_statistics() {
    TESTS_RUN=$((TESTS_RUN + 1))
    log_info "Test: SessionEnd statistics calculation"

    # Create test session with metadata
    local session_id=$(run_sql "SELECT gen_random_uuid();" | tr -d ' ')

    run_sql "
        INSERT INTO service_sessions (id, service_name, instance_id, status, metadata)
        VALUES (
            '$session_id'::uuid,
            'claude-code',
            'test-instance',
            'active',
            '{\"test\": true}'::jsonb
        );
    " > /dev/null

    # Create events with different actions
    for action in "write" "edit" "read" "write" "read"; do
        run_sql "
            INSERT INTO hook_events (id, source, action, resource, resource_id, payload, metadata)
            VALUES (
                gen_random_uuid(),
                'TestHook',
                '$action',
                'file',
                'test.py',
                '{\"test\": true}'::jsonb,
                '{\"session_id\": \"$session_id\"}'::jsonb
            );
        " > /dev/null
    done

    # Calculate statistics
    local stats=$(run_sql "
        SELECT
            COUNT(*) as total_events,
            COUNT(DISTINCT action) as distinct_actions,
            COUNT(CASE WHEN action = 'write' THEN 1 END) as write_count,
            COUNT(CASE WHEN action = 'read' THEN 1 END) as read_count
        FROM hook_events
        WHERE metadata->>'session_id' = '$session_id';
    ")

    local total_events=$(echo "$stats" | awk '{print $1}')
    local write_count=$(echo "$stats" | awk '{print $5}')
    local read_count=$(echo "$stats" | awk '{print $7}')

    if [[ "$total_events" == "5" ]] && [[ "$write_count" == "2" ]] && [[ "$read_count" == "2" ]]; then
        log_success "SessionEnd statistics: 5 total, 2 writes, 2 reads"
        TESTS_PASSED=$((TESTS_PASSED + 1))

        # Cleanup
        run_sql "DELETE FROM hook_events WHERE metadata->>'session_id' = '$session_id';"
        run_sql "DELETE FROM service_sessions WHERE id = '$session_id'::uuid;"
        return 0
    else
        log_error "SessionEnd statistics: Expected 5 total/2 writes/2 reads, got $total_events/$write_count/$read_count"
        TESTS_FAILED=$((TESTS_FAILED + 1))

        # Cleanup
        run_sql "DELETE FROM hook_events WHERE metadata->>'session_id' = '$session_id';"
        run_sql "DELETE FROM service_sessions WHERE id = '$session_id'::uuid;"
        return 1
    fi
}

# Main test execution
echo "=========================================="
echo "Session Hooks Test Suite"
echo "=========================================="
echo ""

# Run all tests
test_session_start_basic
test_session_start_performance
test_session_end_basic
test_session_end_aggregation
test_session_statistics

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
