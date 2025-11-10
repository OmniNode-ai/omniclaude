#!/bin/bash
# Functional Test: Agent Routing System
# Tests event-based routing via Kafka with performance validation
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Load environment
if [[ ! -f .env ]]; then
    echo -e "${RED}❌ .env file not found${NC}"
    exit 1
fi

# Export all variables from .env
set -a
source .env
set +a

# Configurable list of local/docker hostnames (can be overridden via environment)
LOCAL_POSTGRES_HOSTS="${LOCAL_POSTGRES_HOSTS:-omninode-bridge-postgres,localhost,127.0.0.1}"

# For host scripts, use REMOTE_INFRASTRUCTURE_IP instead of Docker hostname
if [[ "$LOCAL_POSTGRES_HOSTS" =~ (^|,)"$POSTGRES_HOST"(,|$) ]]; then
    POSTGRES_HOST="${REMOTE_INFRASTRUCTURE_IP}"
fi

# Configurable thresholds (with sensible defaults)
ROUTING_RECENT_HOURS="${ROUTING_RECENT_HOURS:-24}"

echo "=== Agent Routing Functional Test ==="
echo "Timestamp: $(date)"
echo ""

# Track test results
PASSED=0
FAILED=0
WARNINGS=0

# Helper functions
pass() {
    echo -e "  ${GREEN}✅${NC} $1"
    PASSED=$((PASSED + 1))
}

fail() {
    echo -e "  ${RED}❌${NC} $1"
    FAILED=$((FAILED + 1))
}

warn() {
    echo -e "  ${YELLOW}⚠️${NC}  $1"
    WARNINGS=$((WARNINGS + 1))
}

# 1. Check routing service container
echo "1. Checking Routing Service:"
if docker ps --format '{{.Names}}' | grep -qE "router.*consumer|router-consumer"; then
    CONTAINER_NAME=$(docker ps --format '{{.Names}}' | grep -E "router.*consumer|router-consumer")
    CONTAINER_STATUS=$(docker inspect -f '{{.State.Status}}' "$CONTAINER_NAME" 2>/dev/null || echo "unknown")
    if [[ "$CONTAINER_STATUS" == "running" ]]; then
        pass "Router consumer container running: $CONTAINER_NAME"
    else
        fail "Router consumer container not running (status: $CONTAINER_STATUS)"
    fi
else
    fail "Router consumer container not found"
fi

# 2. Check Kafka topics
echo ""
echo "2. Checking Routing Topics:"
KAFKA_CHECK=0

# First check if kcat is available
if ! command -v kcat &> /dev/null; then
    warn "kcat not installed (skipping Kafka topic checks)"
else
    # Get topic list once with timeout
    KAFKA_TOPICS=$(timeout 5s kcat -L -b "$KAFKA_BOOTSTRAP_SERVERS" 2>/dev/null || echo "")

    if [[ -z "$KAFKA_TOPICS" ]]; then
        warn "Cannot connect to Kafka at $KAFKA_BOOTSTRAP_SERVERS (check connectivity)"
    else
        for topic in "agent.routing.requested.v1" "agent.routing.completed.v1" "agent.routing.failed.v1"; do
            if echo "$KAFKA_TOPICS" | grep -q "$topic"; then
                pass "$topic exists"
                KAFKA_CHECK=$((KAFKA_CHECK + 1))
            else
                warn "$topic missing (routing may not work)"
            fi
        done
    fi
fi

if [[ $KAFKA_CHECK -eq 3 ]]; then
    pass "All routing topics available"
else
    warn "Only $KAFKA_CHECK/3 routing topics found"
fi

# 3. Check database tables
echo ""
echo "3. Checking Routing Database Tables:"
DB_CHECK=0
for table in "agent_routing_decisions" "router_performance_metrics" "agent_manifest_injections"; do
    if PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DATABASE" -t -c "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='$table')" 2>/dev/null | grep -q 't'; then
        pass "$table exists"
        DB_CHECK=$((DB_CHECK + 1))
    else
        fail "$table missing"
    fi
done

# 4. Check recent routing activity
echo ""
echo "4. Checking Recent Routing Activity:"
RECENT_ROUTES=$(PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DATABASE" -t -c "SELECT COUNT(*) FROM agent_routing_decisions WHERE created_at > NOW() - INTERVAL '${ROUTING_RECENT_HOURS} hours'" 2>/dev/null | tr -d ' ' || echo "0")

if [[ "$RECENT_ROUTES" -gt "0" ]]; then
    pass "$RECENT_ROUTES routing decisions in last ${ROUTING_RECENT_HOURS}h"

    # Get success rate
    SUCCESS_RATE=$(PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DATABASE" -t -c "SELECT ROUND(COUNT(*) FILTER (WHERE selected_agent IS NOT NULL)::numeric / COUNT(*)::numeric * 100, 2) FROM agent_routing_decisions WHERE created_at > NOW() - INTERVAL '${ROUTING_RECENT_HOURS} hours'" 2>/dev/null | tr -d ' ' || echo "N/A")

    if [[ "$SUCCESS_RATE" != "N/A" ]]; then
        if (( $(echo "$SUCCESS_RATE > 90" | bc -l) )); then
            pass "Success rate: ${SUCCESS_RATE}%"
        elif (( $(echo "$SUCCESS_RATE > 70" | bc -l) )); then
            warn "Success rate: ${SUCCESS_RATE}% (target: >90%)"
        else
            fail "Success rate: ${SUCCESS_RATE}% (critical: <70%)"
        fi
    fi
else
    warn "No routing decisions in last ${ROUTING_RECENT_HOURS}h (system may be idle)"
fi

# 5. Check routing performance
echo ""
echo "5. Checking Routing Performance:"
if [[ "$RECENT_ROUTES" -gt "0" ]]; then
    # Average routing time
    AVG_TIME=$(PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DATABASE" -t -c "SELECT ROUND(AVG(routing_time_ms)::numeric, 2) FROM agent_routing_decisions WHERE created_at > NOW() - INTERVAL '${ROUTING_RECENT_HOURS} hours' AND routing_time_ms IS NOT NULL" 2>/dev/null | tr -d ' ' || echo "N/A")

    if [[ "$AVG_TIME" != "N/A" ]] && [[ "$AVG_TIME" != "" ]]; then
        # Target: <10ms excellent, <100ms acceptable
        if (( $(echo "$AVG_TIME < 10" | bc -l) )); then
            pass "Average routing time: ${AVG_TIME}ms (excellent)"
        elif (( $(echo "$AVG_TIME < 100" | bc -l) )); then
            pass "Average routing time: ${AVG_TIME}ms (acceptable)"
        else
            warn "Average routing time: ${AVG_TIME}ms (target: <100ms)"
        fi
    else
        warn "No routing time data available"
    fi

    # P95 latency
    P95_TIME=$(PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DATABASE" -t -c "SELECT ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY routing_time_ms)::numeric, 2) FROM agent_routing_decisions WHERE created_at > NOW() - INTERVAL '${ROUTING_RECENT_HOURS} hours' AND routing_time_ms IS NOT NULL" 2>/dev/null | tr -d ' ' || echo "N/A")

    if [[ "$P95_TIME" != "N/A" ]] && [[ "$P95_TIME" != "" ]]; then
        if (( $(echo "$P95_TIME < 50" | bc -l) )); then
            pass "P95 latency: ${P95_TIME}ms (excellent)"
        elif (( $(echo "$P95_TIME < 200" | bc -l) )); then
            pass "P95 latency: ${P95_TIME}ms (acceptable)"
        else
            warn "P95 latency: ${P95_TIME}ms (target: <200ms)"
        fi
    fi
else
    warn "No performance data (no routing activity)"
fi

# 6. Test routing query (if Python available)
echo ""
echo "6. Testing Routing Query:"
if command -v python3 &> /dev/null; then
    # Test if routing module exists
    if python3 -c "import sys; sys.path.insert(0, '/Volumes/PRO-G40/Code/omniclaude'); from agents.lib.routing_event_client import route_via_events; print('OK')" 2>/dev/null | grep -q "OK"; then
        pass "Routing event client module available"

        # Try actual routing request (with timeout)
        echo "  Testing live routing request..."
        ROUTING_TEST=$(timeout 10s python3 << 'EOF' 2>&1 || echo "TIMEOUT"
import sys
import asyncio
sys.path.insert(0, '/Volumes/PRO-G40/Code/omniclaude')

async def test_routing():
    try:
        from agents.lib.routing_event_client import route_via_events
        import time

        start = time.time()
        recommendations = await route_via_events(
            user_request="Write a Python function to test routing",
            max_recommendations=3
        )
        elapsed = (time.time() - start) * 1000

        if recommendations and len(recommendations) > 0:
            print(f"OK:{len(recommendations)}:{elapsed:.2f}")
        else:
            print("NO_RECOMMENDATIONS")
    except Exception as e:
        print(f"ERROR:{str(e)}")

asyncio.run(test_routing())
EOF
)

        if echo "$ROUTING_TEST" | grep -q "^OK:"; then
            RECS=$(echo "$ROUTING_TEST" | cut -d: -f2)
            TIME=$(echo "$ROUTING_TEST" | cut -d: -f3)
            pass "Live routing test successful ($RECS recommendations in ${TIME}ms)"
        elif echo "$ROUTING_TEST" | grep -q "TIMEOUT"; then
            fail "Routing request timeout (>10s)"
        elif echo "$ROUTING_TEST" | grep -q "ERROR:"; then
            ERROR_MSG=$(echo "$ROUTING_TEST" | cut -d: -f2-)
            fail "Routing error: $ERROR_MSG"
        else
            warn "Routing test inconclusive: $ROUTING_TEST"
        fi
    else
        warn "Routing event client not available (check installation)"
    fi
else
    warn "Python3 not available (skipping live test)"
fi

# 7. Check manifest injection integration
echo ""
echo "7. Checking Manifest Injection Integration:"
RECENT_MANIFESTS=$(PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DATABASE" -t -c "SELECT COUNT(*) FROM agent_manifest_injections WHERE created_at > NOW() - INTERVAL '${ROUTING_RECENT_HOURS} hours'" 2>/dev/null | tr -d ' ' || echo "0")

if [[ "$RECENT_MANIFESTS" -gt "0" ]]; then
    pass "$RECENT_MANIFESTS manifest injections in last ${ROUTING_RECENT_HOURS}h"

    # Check average query time
    AVG_MANIFEST_TIME=$(PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DATABASE" -t -c "SELECT ROUND(AVG(total_query_time_ms)::numeric, 2) FROM agent_manifest_injections WHERE created_at > NOW() - INTERVAL '${ROUTING_RECENT_HOURS} hours' AND total_query_time_ms IS NOT NULL" 2>/dev/null | tr -d ' ' || echo "N/A")

    if [[ "$AVG_MANIFEST_TIME" != "N/A" ]] && [[ "$AVG_MANIFEST_TIME" != "" ]]; then
        if (( $(echo "$AVG_MANIFEST_TIME < 2000" | bc -l) )); then
            pass "Average manifest query time: ${AVG_MANIFEST_TIME}ms (excellent)"
        elif (( $(echo "$AVG_MANIFEST_TIME < 5000" | bc -l) )); then
            warn "Average manifest query time: ${AVG_MANIFEST_TIME}ms (target: <2000ms)"
        else
            fail "Average manifest query time: ${AVG_MANIFEST_TIME}ms (critical: >5000ms)"
        fi
    fi
else
    warn "No manifest injections in last ${ROUTING_RECENT_HOURS}h (system may be idle)"
fi

# Summary
echo ""
echo "=== Test Summary ==="
echo "Passed:   $PASSED"
echo "Failed:   $FAILED"
echo "Warnings: $WARNINGS"
echo ""

if [[ $FAILED -eq 0 ]]; then
    echo -e "${GREEN}✅ Agent Routing Functional Test PASSED${NC}"
    exit 0
else
    echo -e "${RED}❌ Agent Routing Functional Test FAILED${NC}"
    echo "Please review failures above and check:"
    echo "  1. Router consumer container: docker logs <router-consumer>"
    echo "  2. Kafka connectivity: kcat -L -b \$KAFKA_BOOTSTRAP_SERVERS"
    echo "  3. Database connectivity: psql -h \$POSTGRES_HOST -p \$POSTGRES_PORT -U \$POSTGRES_USER -d \$POSTGRES_DATABASE"
    exit 1
fi
