#!/bin/bash
# Functional Test: PostgreSQL Database
# Tests actual database operations, not just container status
set -e

# Load environment variables
if [ ! -f .env ]; then
    echo "❌ Error: .env file not found"
    echo "Please run from project root with .env file present"
    exit 1
fi

source .env

# Verify required env vars are set
if [ -z "$POSTGRES_HOST" ] || [ -z "$POSTGRES_PORT" ] || [ -z "$POSTGRES_USER" ] || [ -z "$POSTGRES_DATABASE" ] || [ -z "$POSTGRES_PASSWORD" ]; then
    echo "❌ Error: Missing required PostgreSQL environment variables"
    echo "Required: POSTGRES_HOST, POSTGRES_PORT, POSTGRES_USER, POSTGRES_DATABASE, POSTGRES_PASSWORD"
    exit 1
fi

echo "=== PostgreSQL Functional Test ==="
echo "Host: $POSTGRES_HOST:$POSTGRES_PORT"
echo "Database: $POSTGRES_DATABASE"
echo "User: $POSTGRES_USER"
echo ""

# 1. Test connectivity
echo -n "Testing PostgreSQL connectivity... "
if PGPASSWORD=$POSTGRES_PASSWORD psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DATABASE -c "SELECT 1" > /dev/null 2>&1; then
    echo "✅ Connected"
else
    echo "❌ Failed"
    echo "Could not connect to PostgreSQL database"
    exit 1
fi

# 2. Check tables exist
echo ""
echo "Verifying critical tables:"
TABLES=("agent_actions" "agent_routing_decisions" "agent_manifest_injections" "agent_execution_logs")
MISSING_TABLES=0

for table in "${TABLES[@]}"; do
    if PGPASSWORD=$POSTGRES_PASSWORD psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DATABASE -t -c "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='$table')" | grep -q 't'; then
        echo "  ✅ $table exists"
    else
        echo "  ❌ $table missing"
        MISSING_TABLES=$((MISSING_TABLES + 1))
    fi
done

if [ $MISSING_TABLES -gt 0 ]; then
    echo ""
    echo "❌ Error: $MISSING_TABLES critical table(s) missing"
    exit 1
fi

# 3. Test write/read operations
echo ""
echo "Testing write/read/delete operations:"
TEST_ID="$(uuidgen)"

# Write operation
echo -n "  Writing test record... "
if PGPASSWORD=$POSTGRES_PASSWORD psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DATABASE -c "INSERT INTO agent_actions (correlation_id, agent_name, action_type, action_name) VALUES ('$TEST_ID', 'test-agent', 'tool_call', 'functional_test')" > /dev/null 2>&1; then
    echo "✅ Write successful"
else
    echo "❌ Write failed"
    exit 1
fi

# Read operation
echo -n "  Reading test record... "
COUNT=$(PGPASSWORD=$POSTGRES_PASSWORD psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DATABASE -t -c "SELECT COUNT(*) FROM agent_actions WHERE correlation_id='$TEST_ID'" | tr -d ' ')
if [[ "$COUNT" == "1" ]]; then
    echo "✅ Read successful (found record)"
else
    echo "❌ Read failed (expected 1 record, found $COUNT)"
    exit 1
fi

# Verify data integrity
echo -n "  Verifying data integrity... "
AGENT_NAME=$(PGPASSWORD=$POSTGRES_PASSWORD psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DATABASE -t -c "SELECT agent_name FROM agent_actions WHERE correlation_id='$TEST_ID'" | tr -d ' ')
if [[ "$AGENT_NAME" == "test-agent" ]]; then
    echo "✅ Data integrity verified"
else
    echo "❌ Data integrity check failed (expected 'test-agent', got '$AGENT_NAME')"
    exit 1
fi

# Cleanup
echo -n "  Cleaning up test data... "
if PGPASSWORD=$POSTGRES_PASSWORD psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DATABASE -c "DELETE FROM agent_actions WHERE correlation_id='$TEST_ID'" > /dev/null 2>&1; then
    echo "✅ Cleaned"
else
    echo "❌ Cleanup failed"
    exit 1
fi

# 4. Performance checks
echo ""
echo "Performance checks:"

# Check recent activity
echo -n "  Checking recent activity... "
RECENT=$(PGPASSWORD=$POSTGRES_PASSWORD psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DATABASE -t -c "SELECT COUNT(*) FROM agent_actions WHERE created_at > NOW() - INTERVAL '24 hours'" | tr -d ' ')
echo "✅ $RECENT actions in last 24h"

# Measure query latency
echo -n "  Measuring query latency... "
START_TIME=$(date +%s%N)
PGPASSWORD=$POSTGRES_PASSWORD psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DATABASE -c "SELECT COUNT(*) FROM agent_actions" > /dev/null 2>&1
END_TIME=$(date +%s%N)
LATENCY_MS=$(( (END_TIME - START_TIME) / 1000000 ))

if [ $LATENCY_MS -lt 1000 ]; then
    echo "✅ ${LATENCY_MS}ms (excellent)"
elif [ $LATENCY_MS -lt 3000 ]; then
    echo "⚠️  ${LATENCY_MS}ms (acceptable)"
else
    echo "❌ ${LATENCY_MS}ms (slow)"
fi

# Check for slow queries (optional - requires pg_stat_statements extension)
echo -n "  Checking for slow queries... "
SLOW_QUERY_COUNT=$(PGPASSWORD=$POSTGRES_PASSWORD psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DATABASE -t -c "SELECT COUNT(*) FROM pg_stat_activity WHERE state = 'active' AND query_start < NOW() - INTERVAL '5 seconds' AND query NOT LIKE '%pg_stat_activity%'" 2>/dev/null | tr -d ' ' || echo "0")
if [ "$SLOW_QUERY_COUNT" == "0" ]; then
    echo "✅ No slow queries detected"
else
    echo "⚠️  $SLOW_QUERY_COUNT slow query(ies) detected"
fi

# Check connection count
echo -n "  Checking connection pool... "
ACTIVE_CONNECTIONS=$(PGPASSWORD=$POSTGRES_PASSWORD psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DATABASE -t -c "SELECT COUNT(*) FROM pg_stat_activity WHERE datname = '$POSTGRES_DATABASE'" | tr -d ' ')
echo "✅ $ACTIVE_CONNECTIONS active connection(s)"

echo ""
echo "=== PostgreSQL Functional Test PASSED ==="
echo "All database operations working correctly"
