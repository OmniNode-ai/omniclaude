#!/bin/bash
# validate_monitoring_indexes.sh
# Validates that monitoring performance indexes are working correctly
# Related: agents/parallel_execution/migrations/007_add_monitoring_indexes.sql

set -e

# Database configuration
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5436}"
DB_NAME="${DB_NAME:-omninode_bridge}"
DB_USER="${DB_USER:-postgres}"
export PGPASSWORD="${DB_PASSWORD:-omninode-bridge-postgres-dev-2024}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper function to run SQL query
run_sql() {
    psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -A -c "$1"
}

# Helper function to print status
print_status() {
    local status=$1
    local message=$2

    case $status in
        "pass")
            echo -e "${GREEN}✅ PASS${NC}: $message"
            ;;
        "fail")
            echo -e "${RED}❌ FAIL${NC}: $message"
            ;;
        "warn")
            echo -e "${YELLOW}⚠️  WARN${NC}: $message"
            ;;
        "info")
            echo -e "${BLUE}ℹ️  INFO${NC}: $message"
            ;;
    esac
}

echo "========================================"
echo "Hook Events Monitoring Index Validator"
echo "========================================"
echo ""

# Step 1: Check if indexes exist
print_status "info" "Step 1: Verifying index existence..."
echo ""

indexes_to_check=(
    "idx_hook_events_correlation_id"
    "idx_hook_events_session_all"
    "idx_hook_events_resource_id"
)

all_indexes_exist=true

for index in "${indexes_to_check[@]}"; do
    result=$(run_sql "SELECT COUNT(*) FROM pg_indexes WHERE tablename = 'hook_events' AND indexname = '$index';")

    if [ "$result" = "1" ]; then
        print_status "pass" "Index $index exists"
    else
        print_status "fail" "Index $index does NOT exist"
        all_indexes_exist=false
    fi
done

echo ""

if [ "$all_indexes_exist" = false ]; then
    print_status "fail" "Not all indexes exist. Please run migration 007_add_monitoring_indexes.sql"
    exit 1
fi

# Step 2: Check index sizes
print_status "info" "Step 2: Checking index sizes..."
echo ""

size_query="
SELECT
    indexname,
    pg_size_pretty(pg_relation_size(indexrelid)) as index_size,
    idx_scan as index_scans,
    idx_tup_read as tuples_read
FROM pg_stat_user_indexes
WHERE tablename = 'hook_events'
AND indexname IN ('idx_hook_events_correlation_id', 'idx_hook_events_session_all', 'idx_hook_events_resource_id')
ORDER BY pg_relation_size(indexrelid) DESC;
"

run_sql "$size_query" | while IFS='|' read -r indexname size scans tuples; do
    print_status "info" "$indexname: Size=$size, Scans=$scans, Tuples=$tuples"
done

echo ""

# Step 3: Test correlation_id index performance
print_status "info" "Step 3: Testing correlation_id index performance..."
echo ""

# Insert test data if needed
test_correlation_id="test-validate-$(date +%s)"
run_sql "
INSERT INTO hook_events (id, source, action, resource, resource_id, payload, metadata)
VALUES (
    gen_random_uuid(),
    'UserPromptSubmit',
    'test_validation',
    'test',
    'test-resource',
    '{}'::jsonb,
    '{\"correlation_id\": \"$test_correlation_id\"}'::jsonb
);
" > /dev/null

# Test query with EXPLAIN ANALYZE
explain_output=$(run_sql "EXPLAIN (ANALYZE, FORMAT TEXT) SELECT * FROM hook_events WHERE metadata->>'correlation_id' = '$test_correlation_id' LIMIT 1;")

if echo "$explain_output" | grep -q "idx_hook_events_correlation_id"; then
    execution_time=$(echo "$explain_output" | grep "Execution Time" | sed 's/.*Execution Time: \([0-9.]*\).*/\1/')

    if [ -n "$execution_time" ]; then
        if (( $(echo "$execution_time < 10" | bc -l) )); then
            print_status "pass" "correlation_id index used, execution time: ${execution_time}ms (<10ms target)"
        else
            print_status "warn" "correlation_id index used, but execution time: ${execution_time}ms (>10ms target)"
        fi
    else
        print_status "pass" "correlation_id index is being used"
    fi
else
    print_status "fail" "correlation_id index NOT being used (full table scan detected)"
fi

# Cleanup test data
run_sql "DELETE FROM hook_events WHERE metadata->>'correlation_id' = '$test_correlation_id';" > /dev/null

echo ""

# Step 4: Test session_id index performance
print_status "info" "Step 4: Testing session_id index performance (all sources)..."
echo ""

# Insert test data
test_session_id="test-session-$(date +%s)"
run_sql "
INSERT INTO hook_events (id, source, action, resource, resource_id, payload, metadata)
VALUES (
    gen_random_uuid(),
    'PreToolUse',
    'test_validation',
    'test',
    'test-resource',
    '{}'::jsonb,
    '{\"session_id\": \"$test_session_id\"}'::jsonb
);
" > /dev/null

# Test query with EXPLAIN ANALYZE
explain_output=$(run_sql "EXPLAIN (ANALYZE, FORMAT TEXT) SELECT COUNT(*) FROM hook_events WHERE metadata->>'session_id' = '$test_session_id';")

if echo "$explain_output" | grep -q "idx_hook_events_session_all"; then
    execution_time=$(echo "$explain_output" | grep "Execution Time" | sed 's/.*Execution Time: \([0-9.]*\).*/\1/')

    if [ -n "$execution_time" ]; then
        if (( $(echo "$execution_time < 15" | bc -l) )); then
            print_status "pass" "session_id index used, execution time: ${execution_time}ms (<15ms target)"
        else
            print_status "warn" "session_id index used, but execution time: ${execution_time}ms (>15ms target)"
        fi
    else
        print_status "pass" "session_id index is being used"
    fi
else
    print_status "fail" "session_id index NOT being used (full table scan detected)"
fi

# Cleanup test data
run_sql "DELETE FROM hook_events WHERE metadata->>'session_id' = '$test_session_id';" > /dev/null

echo ""

# Step 5: Test resource_id index performance
print_status "info" "Step 5: Testing resource_id index performance..."
echo ""

# Insert test data
test_resource_id="TestTool-$(date +%s)"
run_sql "
INSERT INTO hook_events (id, source, action, resource, resource_id, payload, metadata)
VALUES (
    gen_random_uuid(),
    'PostToolUse',
    'test_validation',
    'tool',
    '$test_resource_id',
    '{}'::jsonb,
    '{}'::jsonb
);
" > /dev/null

# Test query with EXPLAIN ANALYZE
explain_output=$(run_sql "EXPLAIN (ANALYZE, FORMAT TEXT) SELECT * FROM hook_events WHERE resource_id = '$test_resource_id' AND source = 'PostToolUse' ORDER BY created_at DESC LIMIT 10;")

if echo "$explain_output" | grep -q "idx_hook_events_resource_id"; then
    execution_time=$(echo "$explain_output" | grep "Execution Time" | sed 's/.*Execution Time: \([0-9.]*\).*/\1/')

    if [ -n "$execution_time" ]; then
        if (( $(echo "$execution_time < 10" | bc -l) )); then
            print_status "pass" "resource_id index used, execution time: ${execution_time}ms (<10ms target)"
        else
            print_status "warn" "resource_id index used, but execution time: ${execution_time}ms (>10ms target)"
        fi
    else
        print_status "pass" "resource_id index is being used"
    fi
else
    print_status "fail" "resource_id index NOT being used"
fi

# Cleanup test data
run_sql "DELETE FROM hook_events WHERE resource_id = '$test_resource_id';" > /dev/null

echo ""

# Step 6: Summary
print_status "info" "Step 6: Validation Summary"
echo ""

total_indexes=$(run_sql "SELECT COUNT(*) FROM pg_indexes WHERE tablename = 'hook_events';")
print_status "info" "Total indexes on hook_events: $total_indexes"

echo ""

# Check migration metadata
migration_applied=$(run_sql "SELECT COUNT(*) FROM schema_migrations WHERE version = 7;")
if [ "$migration_applied" = "1" ]; then
    applied_at=$(run_sql "SELECT applied_at FROM schema_migrations WHERE version = 7;")
    print_status "pass" "Migration 007 applied at: $applied_at"
else
    print_status "warn" "Migration 007 not recorded in schema_migrations table"
fi

echo ""
echo "========================================"
echo "Validation Complete"
echo "========================================"

# Exit with success
exit 0
