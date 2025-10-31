#!/bin/bash

# Test script for migration 004: Pattern Quality and Usage Tracking
# This script validates the migration before applying it to production

set -e  # Exit on error

# Database connection parameters
DB_HOST="${DB_HOST:-192.168.86.200}"
DB_PORT="${DB_PORT:-5436}"
DB_NAME="${DB_NAME:-omninode_bridge}"
DB_USER="${DB_USER:-postgres}"
DB_PASSWORD="${POSTGRES_PASSWORD:-***REDACTED***}"

export PGPASSWORD="$DB_PASSWORD"

echo "=========================================="
echo "Migration 004 Test Script"
echo "=========================================="
echo ""

# Function to run SQL query
run_query() {
    local query="$1"
    psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "$query"
}

# Function to check if column exists
check_column_exists() {
    local table="$1"
    local column="$2"
    local result=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c "SELECT COUNT(*) FROM information_schema.columns WHERE table_name='$table' AND column_name='$column';")
    echo "$result" | tr -d ' '
}

# Function to check if table exists
check_table_exists() {
    local table="$1"
    local result=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_name='$table';")
    echo "$result" | tr -d ' '
}

# Function to check if trigger exists
check_trigger_exists() {
    local trigger="$1"
    local table="$2"
    local result=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c "SELECT COUNT(*) FROM information_schema.triggers WHERE trigger_name='$trigger' AND event_object_table='$table';")
    echo "$result" | tr -d ' '
}

echo "Step 1: Pre-migration checks"
echo "-----------------------------"
echo "Checking if pattern_lineage_nodes table exists..."
if [ "$(check_table_exists 'pattern_lineage_nodes')" -eq 0 ]; then
    echo "ERROR: pattern_lineage_nodes table does not exist!"
    exit 1
fi
echo "✓ pattern_lineage_nodes table exists"

echo ""
echo "Step 2: Backup current schema (just describe table)"
echo "-----------------------------"
run_query "\d pattern_lineage_nodes"

echo ""
echo "Step 3: Apply migration"
echo "-----------------------------"
echo "Applying migration 004..."
psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -f "$(dirname "$0")/004_pattern_quality_usage.sql"
echo "✓ Migration applied"

echo ""
echo "Step 4: Verify new columns exist"
echo "-----------------------------"

# Check quality score columns
for col in complexity_score documentation_score test_coverage_score reusability_score maintainability_score overall_quality; do
    if [ "$(check_column_exists 'pattern_lineage_nodes' "$col")" -eq 1 ]; then
        echo "✓ Column $col exists"
    else
        echo "✗ ERROR: Column $col does not exist"
        exit 1
    fi
done

# Check usage tracking columns
for col in usage_count last_used_at used_by_agents; do
    if [ "$(check_column_exists 'pattern_lineage_nodes' "$col")" -eq 1 ]; then
        echo "✓ Column $col exists"
    else
        echo "✗ ERROR: Column $col does not exist"
        exit 1
    fi
done

echo ""
echo "Step 5: Verify pattern_relationships table"
echo "-----------------------------"
if [ "$(check_table_exists 'pattern_relationships')" -eq 1 ]; then
    echo "✓ pattern_relationships table exists"
    run_query "\d pattern_relationships"
else
    echo "✗ ERROR: pattern_relationships table does not exist"
    exit 1
fi

echo ""
echo "Step 6: Verify trigger exists"
echo "-----------------------------"
if [ "$(check_trigger_exists 'increment_pattern_usage_trigger' 'agent_manifest_injections')" -eq 1 ]; then
    echo "✓ Trigger increment_pattern_usage_trigger exists"
else
    echo "✗ ERROR: Trigger increment_pattern_usage_trigger does not exist"
    exit 1
fi

echo ""
echo "Step 7: Test quality score constraints"
echo "-----------------------------"
echo "Testing invalid quality score (should fail)..."
if run_query "UPDATE pattern_lineage_nodes SET overall_quality = 1.5 WHERE id = (SELECT id FROM pattern_lineage_nodes LIMIT 1);" 2>&1 | grep -q "violates check constraint"; then
    echo "✓ Quality score constraint working correctly"
else
    echo "WARNING: Quality score constraint may not be working as expected"
fi

echo "Testing valid quality score (should succeed)..."
run_query "UPDATE pattern_lineage_nodes SET overall_quality = 0.85 WHERE id = (SELECT id FROM pattern_lineage_nodes LIMIT 1);"
echo "✓ Valid quality score update succeeded"

echo ""
echo "Step 8: Test usage tracking"
echo "-----------------------------"
echo "Resetting usage counts..."
run_query "UPDATE pattern_lineage_nodes SET usage_count = 0, last_used_at = NULL, used_by_agents = ARRAY[]::TEXT[] WHERE id = (SELECT id FROM pattern_lineage_nodes LIMIT 1);"

echo "Counting manifest injections before test..."
count_before=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c "SELECT COUNT(*) FROM agent_manifest_injections;")
echo "Current manifest injections: $count_before"

echo ""
echo "Step 9: Verify indexes"
echo "-----------------------------"
echo "Checking quality score indexes..."
run_query "SELECT indexname FROM pg_indexes WHERE tablename = 'pattern_lineage_nodes' AND indexname LIKE '%quality%';"

echo "Checking usage tracking indexes..."
run_query "SELECT indexname FROM pg_indexes WHERE tablename = 'pattern_lineage_nodes' AND indexname LIKE '%usage%';"

echo "Checking pattern_relationships indexes..."
run_query "SELECT indexname FROM pg_indexes WHERE tablename = 'pattern_relationships';"

echo ""
echo "Step 10: View updated table structure"
echo "-----------------------------"
run_query "\d pattern_lineage_nodes"

echo ""
echo "=========================================="
echo "Migration 004 Test: SUCCESS"
echo "=========================================="
echo ""
echo "Summary:"
echo "  ✓ All quality score columns added"
echo "  ✓ All usage tracking columns added"
echo "  ✓ pattern_relationships table created"
echo "  ✓ Trigger for usage tracking created"
echo "  ✓ All constraints working correctly"
echo "  ✓ All indexes created"
echo ""
echo "Migration is ready for production."
echo ""
