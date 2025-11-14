#!/bin/bash
# Comprehensive Database System Verification Script
# Validates ALL tables, views, schema, data integrity, and performance
#
# Usage: ./scripts/verify_database_system.sh
# Exit codes: 0=success, 1=failures detected, 2=fatal error

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Counters
TOTAL_CHECKS=0
PASSED_CHECKS=0
FAILED_CHECKS=0
WARNING_CHECKS=0

# Get repo root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
mkdir -p "$REPO_ROOT/tmp"

# Load environment
if [ ! -f "$REPO_ROOT/.env" ]; then
    echo -e "${RED}❌ Error: .env file not found${NC}"
    echo "Please run from project root with .env file present"
    exit 2
fi

source .env

# Verify required env vars
if [ -z "$POSTGRES_USER" ] || [ -z "$POSTGRES_DATABASE" ]; then
    echo -e "${RED}❌ Error: Missing required PostgreSQL environment variables${NC}"
    echo "Required: POSTGRES_USER, POSTGRES_DATABASE"
    exit 2
fi

# Determine connection parameters
# Use environment variables if available, fallback to defaults for backward compatibility
# This supports different environments (Docker, remote, local) without breaking existing setups
DB_HOST="${POSTGRES_HOST:-192.168.86.200}"
DB_PORT="${POSTGRES_PORT:-5436}"
DB_NAME="$POSTGRES_DATABASE"
DB_USER="$POSTGRES_USER"

# Get password from environment
if [ -n "$POSTGRES_PASSWORD" ]; then
    DB_PASSWORD="$POSTGRES_PASSWORD"
elif [ -n "$TRACEABILITY_DB_PASSWORD" ]; then
    DB_PASSWORD="$TRACEABILITY_DB_PASSWORD"
else
    echo -e "${RED}❌ Error: POSTGRES_PASSWORD not set in .env${NC}"
    exit 2
fi

export PGPASSWORD="$DB_PASSWORD"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  COMPREHENSIVE DATABASE SYSTEM VERIFICATION"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Database: $DB_NAME @ $DB_HOST:$DB_PORT"
echo "User: $DB_USER"
echo "Timestamp: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# Helper functions
check() {
    TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
}

pass() {
    echo -e "${GREEN}✓${NC} $1"
    PASSED_CHECKS=$((PASSED_CHECKS + 1))
}

fail() {
    echo -e "${RED}✗${NC} $1"
    FAILED_CHECKS=$((FAILED_CHECKS + 1))
}

warn() {
    echo -e "${YELLOW}⚠${NC} $1"
    WARNING_CHECKS=$((WARNING_CHECKS + 1))
}

info() {
    echo -e "${CYAN}ℹ${NC} $1"
}

section() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  $1"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION 1: CONNECTIVITY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
section "1. CONNECTIVITY TEST"

check
if psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "SELECT 1" > /dev/null 2>&1; then
    pass "PostgreSQL connection successful"
else
    fail "PostgreSQL connection failed"
    echo -e "${RED}Cannot proceed without database connectivity${NC}"
    exit 2
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION 2: SCHEMA VALIDATION - ALL TABLES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
section "2. SCHEMA VALIDATION - TABLES"

# Core agent observability tables
CORE_TABLES=(
    "agent_actions"
    "agent_routing_decisions"
    "agent_transformation_events"
    "agent_manifest_injections"
    "agent_execution_logs"
    "agent_prompts"
    "agent_intelligence_usage"
    "agent_file_operations"
    "agent_definitions"
)

# Infrastructure and metrics tables
INFRA_TABLES=(
    "router_performance_metrics"
    "event_metrics"
    "event_processing_metrics"
    "generation_performance_metrics"
    "connection_metrics"
    "service_sessions"
    "error_tracking"
    "alert_history"
    "security_audit_log"
)

# Pattern and quality tables
PATTERN_TABLES=(
    "pattern_quality_metrics"
    "pattern_lineage_nodes"
    "pattern_lineage_edges"
    "pattern_lineage_events"
    "pattern_ancestry_cache"
    "pattern_feedback_log"
    "template_cache_metadata"
)

# Node and mixin tables
NODE_TABLES=(
    "node_registrations"
    "mixin_compatibility_matrix"
    "schema_migrations"
    "hook_events"
)

ALL_TABLES=("${CORE_TABLES[@]}" "${INFRA_TABLES[@]}" "${PATTERN_TABLES[@]}" "${NODE_TABLES[@]}")

echo "Checking ${#ALL_TABLES[@]} tables..."
echo ""

MISSING_TABLES=0
for table in "${ALL_TABLES[@]}"; do
    check
    if psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c \
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='$table')" | grep -q 't'; then
        pass "Table exists: $table"
    else
        fail "Table missing: $table"
        MISSING_TABLES=$((MISSING_TABLES + 1))
    fi
done

if [ $MISSING_TABLES -gt 0 ]; then
    warn "Total missing tables: $MISSING_TABLES"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION 3: SCHEMA VALIDATION - CRITICAL VIEWS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
section "3. SCHEMA VALIDATION - VIEWS"

CRITICAL_VIEWS=(
    "v_agent_execution_trace"
    "v_agent_performance"
    "v_manifest_injection_performance"
    "v_routing_decision_accuracy"
    "v_intelligence_effectiveness"
    "v_agent_quality_leaderboard"
    "v_complete_execution_trace"
    "active_errors"
    "recent_debug_traces"
)

echo "Checking ${#CRITICAL_VIEWS[@]} critical views..."
echo ""

MISSING_VIEWS=0
for view in "${CRITICAL_VIEWS[@]}"; do
    check
    if psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c \
        "SELECT EXISTS (SELECT 1 FROM information_schema.views WHERE table_name='$view')" | grep -q 't'; then
        pass "View exists: $view"
    else
        fail "View missing: $view"
        MISSING_VIEWS=$((MISSING_VIEWS + 1))
    fi
done

if [ $MISSING_VIEWS -gt 0 ]; then
    warn "Total missing views: $MISSING_VIEWS"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION 4: COLUMN VALIDATION - CRITICAL TABLES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
section "4. COLUMN VALIDATION"

# agent_actions required columns
check
REQUIRED_COLS=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c \
    "SELECT COUNT(*) FROM information_schema.columns WHERE table_name='agent_actions'
     AND column_name IN ('correlation_id', 'agent_name', 'action_type', 'action_name', 'created_at')" | tr -d ' ')
if [ "$REQUIRED_COLS" == "5" ]; then
    pass "agent_actions has all required columns"
else
    fail "agent_actions missing required columns (found $REQUIRED_COLS/5)"
fi

# agent_routing_decisions required columns
check
REQUIRED_COLS=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c \
    "SELECT COUNT(*) FROM information_schema.columns WHERE table_name='agent_routing_decisions'
     AND column_name IN ('correlation_id', 'user_request', 'selected_agent', 'confidence_score', 'created_at')" | tr -d ' ')
if [ "$REQUIRED_COLS" == "5" ]; then
    pass "agent_routing_decisions has all required columns"
else
    fail "agent_routing_decisions missing required columns (found $REQUIRED_COLS/5)"
fi

# agent_manifest_injections required columns
check
REQUIRED_COLS=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c \
    "SELECT COUNT(*) FROM information_schema.columns WHERE table_name='agent_manifest_injections'
     AND column_name IN ('correlation_id', 'agent_name', 'manifest_version', 'patterns_count', 'created_at')" | tr -d ' ')
if [ "$REQUIRED_COLS" == "5" ]; then
    pass "agent_manifest_injections has all required columns"
else
    fail "agent_manifest_injections missing required columns (found $REQUIRED_COLS/5)"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION 5: DATA INTEGRITY - CONSTRAINTS & INDEXES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
section "5. DATA INTEGRITY"

# Check for primary keys
check
PK_COUNT=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c \
    "SELECT COUNT(*) FROM information_schema.table_constraints
     WHERE constraint_type = 'PRIMARY KEY' AND table_schema = 'public'" | tr -d ' ')
if [ "$PK_COUNT" -ge 25 ]; then
    pass "Primary keys defined: $PK_COUNT"
else
    warn "Few primary keys defined: $PK_COUNT (expected ≥25)"
fi

# Check for foreign keys
check
FK_COUNT=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c \
    "SELECT COUNT(*) FROM information_schema.table_constraints
     WHERE constraint_type = 'FOREIGN KEY' AND table_schema = 'public'" | tr -d ' ')
info "Foreign keys defined: $FK_COUNT"

# Check for indexes
check
INDEX_COUNT=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c \
    "SELECT COUNT(*) FROM pg_indexes WHERE schemaname = 'public'" | tr -d ' ')
if [ "$INDEX_COUNT" -ge 30 ]; then
    pass "Indexes defined: $INDEX_COUNT"
else
    warn "Few indexes defined: $INDEX_COUNT (expected ≥30 for performance)"
fi

# Check for orphaned records (agent_actions without routing decisions)
check
ORPHANED=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c \
    "SELECT COUNT(DISTINCT aa.correlation_id)
     FROM agent_actions aa
     LEFT JOIN agent_routing_decisions ard ON aa.correlation_id = ard.correlation_id
     WHERE ard.correlation_id IS NULL
     AND aa.created_at > NOW() - INTERVAL '7 days'" 2>/dev/null | tr -d ' ' || echo "0")
if [ "$ORPHANED" == "0" ]; then
    pass "No orphaned agent_actions (last 7 days)"
else
    warn "Found $ORPHANED orphaned agent_actions without routing decisions (last 7 days)"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION 6: FUNCTIONAL VALIDATION - CRUD OPERATIONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
section "6. FUNCTIONAL VALIDATION - CRUD OPERATIONS"

# Generate test data
TEST_CORRELATION_ID=$(uuidgen)
TEST_AGENT_NAME="test-db-verify-agent"

# CREATE operation
check
if psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c \
    "INSERT INTO agent_actions (correlation_id, agent_name, action_type, action_name)
     VALUES ('$TEST_CORRELATION_ID', '$TEST_AGENT_NAME', 'tool_call', 'test_operation')" > /dev/null 2>&1; then
    pass "CREATE: Insert test record"
else
    fail "CREATE: Insert failed"
fi

# READ operation
check
COUNT=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c \
    "SELECT COUNT(*) FROM agent_actions WHERE correlation_id='$TEST_CORRELATION_ID'" | tr -d ' ')
if [ "$COUNT" == "1" ]; then
    pass "READ: Test record found"
else
    fail "READ: Expected 1 record, found $COUNT"
fi

# UPDATE operation
check
if psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c \
    "UPDATE agent_actions SET action_name='test_updated' WHERE correlation_id='$TEST_CORRELATION_ID'" > /dev/null 2>&1; then
    pass "UPDATE: Record updated"
else
    fail "UPDATE: Update failed"
fi

# Verify UPDATE
check
UPDATED_NAME=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c \
    "SELECT action_name FROM agent_actions WHERE correlation_id='$TEST_CORRELATION_ID'" | tr -d ' ')
if [ "$UPDATED_NAME" == "test_updated" ]; then
    pass "UPDATE VERIFY: Data integrity preserved"
else
    fail "UPDATE VERIFY: Expected 'test_updated', got '$UPDATED_NAME'"
fi

# DELETE operation
check
if psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c \
    "DELETE FROM agent_actions WHERE correlation_id='$TEST_CORRELATION_ID'" > /dev/null 2>&1; then
    pass "DELETE: Test record cleaned"
else
    fail "DELETE: Cleanup failed"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION 7: ACTION TYPE VALIDATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
section "7. ACTION TYPE VALIDATION"

# Check all 4 action types exist in data
ACTION_TYPES=("tool_call" "decision" "error" "success")
for action_type in "${ACTION_TYPES[@]}"; do
    check
    COUNT=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c \
        "SELECT COUNT(*) FROM agent_actions WHERE action_type='$action_type'
         AND created_at > NOW() - INTERVAL '7 days'" 2>/dev/null | tr -d ' ' || echo "0")
    if [ "$COUNT" -gt 0 ]; then
        pass "Action type '$action_type': $COUNT records (last 7 days)"
    else
        warn "Action type '$action_type': No recent records (last 7 days)"
    fi
done

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION 8: RECENT ACTIVITY VALIDATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
section "8. RECENT ACTIVITY VALIDATION"

# agent_actions activity
check
RECENT_ACTIONS=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c \
    "SELECT COUNT(*) FROM agent_actions WHERE created_at > NOW() - INTERVAL '24 hours'" | tr -d ' ')
info "agent_actions (24h): $RECENT_ACTIONS records"

# agent_routing_decisions activity
check
RECENT_ROUTING=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c \
    "SELECT COUNT(*) FROM agent_routing_decisions WHERE created_at > NOW() - INTERVAL '24 hours'" | tr -d ' ')
info "agent_routing_decisions (24h): $RECENT_ROUTING records"

# agent_manifest_injections activity
check
RECENT_MANIFESTS=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c \
    "SELECT COUNT(*) FROM agent_manifest_injections WHERE created_at > NOW() - INTERVAL '24 hours'" | tr -d ' ')
info "agent_manifest_injections (24h): $RECENT_MANIFESTS records"

# agent_transformation_events activity
check
RECENT_TRANSFORMS=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c \
    "SELECT COUNT(*) FROM agent_transformation_events WHERE created_at > NOW() - INTERVAL '24 hours'" 2>/dev/null | tr -d ' ' || echo "0")
info "agent_transformation_events (24h): $RECENT_TRANSFORMS records"

# Overall activity check
TOTAL_ACTIVITY=$((RECENT_ACTIONS + RECENT_ROUTING + RECENT_MANIFESTS))
if [ $TOTAL_ACTIVITY -gt 0 ]; then
    pass "Database is active (${TOTAL_ACTIVITY} records in last 24h)"
else
    warn "No recent activity detected (last 24h) - may indicate system is idle"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION 9: PERFORMANCE VALIDATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
section "9. PERFORMANCE VALIDATION"

# Query latency test
check
START_TIME=$(date +%s%N)
psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c \
    "SELECT COUNT(*) FROM agent_actions" > /dev/null 2>&1
END_TIME=$(date +%s%N)
LATENCY_MS=$(( (END_TIME - START_TIME) / 1000000 ))

if [ $LATENCY_MS -lt 500 ]; then
    pass "Query latency: ${LATENCY_MS}ms (excellent)"
elif [ $LATENCY_MS -lt 2000 ]; then
    pass "Query latency: ${LATENCY_MS}ms (good)"
elif [ $LATENCY_MS -lt 5000 ]; then
    warn "Query latency: ${LATENCY_MS}ms (acceptable but slow)"
else
    fail "Query latency: ${LATENCY_MS}ms (poor performance)"
fi

# Connection pool check
check
ACTIVE_CONNECTIONS=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c \
    "SELECT COUNT(*) FROM pg_stat_activity WHERE datname = '$DB_NAME'" | tr -d ' ')
if [ "$ACTIVE_CONNECTIONS" -lt 50 ]; then
    pass "Active connections: $ACTIVE_CONNECTIONS (healthy)"
else
    warn "Active connections: $ACTIVE_CONNECTIONS (high - possible connection leak)"
fi

# Database size
check
DB_SIZE=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c \
    "SELECT pg_size_pretty(pg_database_size('$DB_NAME'))" | tr -d ' ')
info "Database size: $DB_SIZE"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION 10: UUID HANDLING VALIDATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
section "10. UUID HANDLING VALIDATION"

# Check if correlation_id columns are UUID type
check
UUID_COLUMNS=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c \
    "SELECT COUNT(*) FROM information_schema.columns
     WHERE table_name IN ('agent_actions', 'agent_routing_decisions', 'agent_manifest_injections')
     AND column_name = 'correlation_id'
     AND data_type = 'uuid'" | tr -d ' ')
if [ "$UUID_COLUMNS" == "3" ]; then
    pass "UUID types: All correlation_id columns use UUID type"
else
    warn "UUID types: Some correlation_id columns may not be UUID type (found $UUID_COLUMNS/3)"
fi

# Test UUID insertion and retrieval
TEST_UUID=$(uuidgen)
check
if psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c \
    "INSERT INTO agent_actions (correlation_id, agent_name, action_type, action_name)
     VALUES ('$TEST_UUID'::uuid, 'uuid-test', 'tool_call', 'uuid_test')" > /dev/null 2>&1; then
    pass "UUID INSERT: Successfully inserted UUID"

    # Verify retrieval (PostgreSQL lowercases UUIDs, so compare case-insensitively)
    RETRIEVED=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c \
        "SELECT correlation_id FROM agent_actions WHERE correlation_id='$TEST_UUID'::uuid" | tr -d ' ')
    RETRIEVED_UPPER=$(echo "$RETRIEVED" | tr '[:lower:]' '[:upper:]')
    TEST_UUID_UPPER=$(echo "$TEST_UUID" | tr '[:lower:]' '[:upper:]')
    if [ "$RETRIEVED_UPPER" == "$TEST_UUID_UPPER" ]; then
        pass "UUID RETRIEVE: Successfully retrieved UUID"
    else
        fail "UUID RETRIEVE: Retrieved UUID doesn't match (expected: $TEST_UUID_UPPER, got: $RETRIEVED_UPPER)"
    fi

    # Cleanup
    psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c \
        "DELETE FROM agent_actions WHERE correlation_id='$TEST_UUID'::uuid" > /dev/null 2>&1
else
    fail "UUID INSERT: Failed to insert UUID"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION 11: VIEW FUNCTIONALITY VALIDATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
section "11. VIEW FUNCTIONALITY VALIDATION"

# Test critical views return data
check
TRACE_COUNT=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c \
    "SELECT COUNT(*) FROM v_agent_execution_trace LIMIT 1" 2>/dev/null | tr -d ' ' || echo "ERROR")
if [ "$TRACE_COUNT" != "ERROR" ]; then
    pass "v_agent_execution_trace: Query successful ($TRACE_COUNT records)"
else
    fail "v_agent_execution_trace: Query failed"
fi

check
PERF_COUNT=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c \
    "SELECT COUNT(*) FROM v_agent_performance LIMIT 1" 2>/dev/null | tr -d ' ' || echo "ERROR")
if [ "$PERF_COUNT" != "ERROR" ]; then
    pass "v_agent_performance: Query successful ($PERF_COUNT records)"
else
    fail "v_agent_performance: Query failed"
fi

check
MANIFEST_COUNT=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c \
    "SELECT COUNT(*) FROM v_manifest_injection_performance LIMIT 1" 2>/dev/null | tr -d ' ' || echo "ERROR")
if [ "$MANIFEST_COUNT" != "ERROR" ]; then
    pass "v_manifest_injection_performance: Query successful ($MANIFEST_COUNT records)"
else
    fail "v_manifest_injection_performance: Query failed"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECTION 12: EDGE CASE VALIDATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
section "12. EDGE CASE VALIDATION"

# NULL constraint validation
check
TEST_UUID=$(uuidgen)
NULL_TEST=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c \
    "INSERT INTO agent_actions (correlation_id, agent_name, action_type)
     VALUES ('$TEST_UUID', 'null-test', NULL)" 2>&1 || echo "NULL_BLOCKED")
if echo "$NULL_TEST" | grep -q "NULL_BLOCKED\|null value"; then
    pass "NULL constraints: action_type NULL blocked correctly"
else
    warn "NULL constraints: action_type NULL may be allowed (should be NOT NULL)"
    # Cleanup if insert succeeded
    psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c \
        "DELETE FROM agent_actions WHERE correlation_id='$TEST_UUID'" > /dev/null 2>&1
fi

# Timestamp consistency
check
FUTURE_TIMESTAMPS=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c \
    "SELECT COUNT(*) FROM agent_actions WHERE created_at > NOW() + INTERVAL '1 hour'" | tr -d ' ')
if [ "$FUTURE_TIMESTAMPS" == "0" ]; then
    pass "Timestamp consistency: No future timestamps detected"
else
    warn "Timestamp consistency: Found $FUTURE_TIMESTAMPS records with future timestamps"
fi

# Large text field handling
check
TEST_UUID=$(uuidgen)
LARGE_TEXT=$(python3 -c "print('A' * 10000)")
if psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c \
    "INSERT INTO agent_actions (correlation_id, agent_name, action_type, action_name, details)
     VALUES ('$TEST_UUID', 'large-text-test', 'tool_call', 'large_text', '$LARGE_TEXT')" > /dev/null 2>&1; then
    pass "Large text handling: Successfully stored 10KB text"
    psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c \
        "DELETE FROM agent_actions WHERE correlation_id='$TEST_UUID'" > /dev/null 2>&1
else
    warn "Large text handling: Failed to store 10KB text (may have size limits)"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SUMMARY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
section "VERIFICATION SUMMARY"

echo ""
echo "Total Checks:    $TOTAL_CHECKS"
echo -e "${GREEN}Passed:${NC}          $PASSED_CHECKS"
if [ $WARNING_CHECKS -gt 0 ]; then
    echo -e "${YELLOW}Warnings:${NC}        $WARNING_CHECKS"
fi
if [ $FAILED_CHECKS -gt 0 ]; then
    echo -e "${RED}Failed:${NC}          $FAILED_CHECKS"
fi
echo ""

# Calculate health score
HEALTH_SCORE=$((PASSED_CHECKS * 100 / TOTAL_CHECKS))
echo -n "Health Score:    "
if [ $HEALTH_SCORE -ge 95 ]; then
    echo -e "${GREEN}${HEALTH_SCORE}%${NC} (Excellent)"
elif [ $HEALTH_SCORE -ge 85 ]; then
    echo -e "${GREEN}${HEALTH_SCORE}%${NC} (Good)"
elif [ $HEALTH_SCORE -ge 70 ]; then
    echo -e "${YELLOW}${HEALTH_SCORE}%${NC} (Acceptable)"
else
    echo -e "${RED}${HEALTH_SCORE}%${NC} (Poor)"
fi
echo ""

# Coverage summary
echo "Coverage Summary:"
echo "  ✓ Tables verified: ${#ALL_TABLES[@]}"
echo "  ✓ Views verified: ${#CRITICAL_VIEWS[@]}"
echo "  ✓ Action types: ${#ACTION_TYPES[@]}"
echo "  ✓ CRUD operations: 4 (Create, Read, Update, Delete)"
echo "  ✓ Performance metrics: 2 (latency, connections)"
echo "  ✓ Edge cases: 3 (NULL, timestamps, large text)"
echo ""

# Save results (use repo tmp directory)
REPORT_FILE="$REPO_ROOT/tmp/database_verification_latest.txt"
{
    echo "Database System Verification Report"
    echo "Generated: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "Database: $DB_NAME @ $DB_HOST:$DB_PORT"
    echo ""
    echo "Results:"
    echo "  Total Checks: $TOTAL_CHECKS"
    echo "  Passed: $PASSED_CHECKS"
    echo "  Warnings: $WARNING_CHECKS"
    echo "  Failed: $FAILED_CHECKS"
    echo "  Health Score: ${HEALTH_SCORE}%"
} > "$REPORT_FILE"

info "Report saved to: $REPORT_FILE"

# Exit code
echo ""
if [ $FAILED_CHECKS -eq 0 ]; then
    echo -e "${GREEN}✓ Database system verification PASSED${NC}"
    echo "All critical checks successful"
    exit 0
else
    echo -e "${RED}✗ Database system verification FAILED${NC}"
    echo "Found $FAILED_CHECKS issue(s). Review failures above."
    exit 1
fi
