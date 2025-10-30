#!/bin/bash
#
# System Health Check Script
#
# Checks the health of:
# - Docker services (archon-*, omninode-*)
# - Kafka connectivity
# - Qdrant collections
# - PostgreSQL connectivity
# - Recent manifest injection quality
# - Intelligence collection status
#
# Usage: ./scripts/health_check.sh
# Output: Saves to /tmp/health_check_latest.txt and appends to /tmp/health_check_history.log
#

set -euo pipefail

# Configuration
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
OUTPUT_FILE="/tmp/health_check_latest.txt"
HISTORY_FILE="/tmp/health_check_history.log"

# Colors for terminal output (disabled in file output)
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Load environment variables from .env if it exists
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    # Source .env file but only export variables we need
    source "$PROJECT_ROOT/.env"
fi

# Connection details (with fallbacks)
KAFKA_HOST="${KAFKA_HOST:-192.168.86.200:9092}"
POSTGRES_HOST="${TRACEABILITY_DB_HOST:-192.168.86.200}"
POSTGRES_PORT="${TRACEABILITY_DB_PORT:-5436}"
POSTGRES_DB="${TRACEABILITY_DB_NAME:-omninode_bridge}"
POSTGRES_USER="${TRACEABILITY_DB_USER:-postgres}"
POSTGRES_PASSWORD="${TRACEABILITY_DB_PASSWORD:-***REDACTED***}"
QDRANT_HOST="${QDRANT_HOST:-localhost}"
QDRANT_PORT="${QDRANT_PORT:-6333}"

# Initialize results
ISSUES_FOUND=0
declare -a ISSUES=()

# Function to add issue
add_issue() {
    ISSUES+=("$1")
    ((ISSUES_FOUND++))
}

# Function to check service health
check_service() {
    local service_name="$1"
    local status=$(docker ps --filter "name=${service_name}" --format "{{.Status}}" 2>/dev/null || echo "not found")

    if [[ "$status" == "not found" || -z "$status" ]]; then
        echo "  ❌ ${service_name} (not running)"
        add_issue "${service_name} container not running"
        return 1
    elif [[ "$status" == *"unhealthy"* ]]; then
        echo "  ⚠️  ${service_name} (unhealthy)"
        add_issue "${service_name} container unhealthy"
        return 1
    else
        echo "  ✅ ${service_name} (healthy)"
        return 0
    fi
}

# Function to check Kafka connectivity
check_kafka() {
    echo ""
    echo "Kafka:"

    # Try to list topics using kafkacat if available
    if command -v kcat &> /dev/null || command -v kafkacat &> /dev/null; then
        local cmd="kcat"
        if ! command -v kcat &> /dev/null; then
            cmd="kafkacat"
        fi

        local topic_count=$($cmd -L -b "$KAFKA_HOST" 2>/dev/null | grep -c "topic \"" || echo "0")
        if [[ $topic_count -gt 0 ]]; then
            echo "  ✅ Kafka: $KAFKA_HOST (connected, $topic_count topics)"
        else
            echo "  ❌ Kafka: $KAFKA_HOST (cannot list topics)"
            add_issue "Kafka connectivity failed"
        fi
    else
        # Fallback: just check if port is open
        if timeout 2 bash -c "cat < /dev/null > /dev/tcp/${KAFKA_HOST%:*}/${KAFKA_HOST#*:}" 2>/dev/null; then
            echo "  ✅ Kafka: $KAFKA_HOST (port open)"
        else
            echo "  ❌ Kafka: $KAFKA_HOST (connection failed)"
            add_issue "Kafka connection failed"
        fi
    fi
}

# Function to check Qdrant
check_qdrant() {
    echo ""
    echo "Qdrant:"

    local response=$(curl -s "http://${QDRANT_HOST}:${QDRANT_PORT}/collections" 2>/dev/null || echo "")

    if [[ -n "$response" ]]; then
        # Parse collection count and vector counts
        local collection_count=$(echo "$response" | jq -r '.result.collections | length' 2>/dev/null || echo "0")

        if [[ $collection_count -gt 0 ]]; then
            echo "  ✅ Qdrant: http://${QDRANT_HOST}:${QDRANT_PORT} (connected, $collection_count collections)"

            # Get vector counts for key collections
            local code_patterns=$(curl -s "http://${QDRANT_HOST}:${QDRANT_PORT}/collections/code_patterns" 2>/dev/null | jq -r '.result.points_count' 2>/dev/null || echo "0")
            local exec_patterns=$(curl -s "http://${QDRANT_HOST}:${QDRANT_PORT}/collections/execution_patterns" 2>/dev/null | jq -r '.result.points_count' 2>/dev/null || echo "0")

            echo "  📊 Collections: code_patterns ($code_patterns vectors), execution_patterns ($exec_patterns vectors)"
        else
            echo "  ⚠️  Qdrant: http://${QDRANT_HOST}:${QDRANT_PORT} (connected, but no collections)"
            add_issue "Qdrant has no collections"
        fi
    else
        echo "  ❌ Qdrant: http://${QDRANT_HOST}:${QDRANT_PORT} (connection failed)"
        add_issue "Qdrant connection failed"
    fi
}

# Function to check PostgreSQL
check_postgres() {
    echo ""
    echo "PostgreSQL:"

    # Check if psql is available
    if ! command -v psql &> /dev/null; then
        echo "  ⚠️  PostgreSQL: Cannot check (psql not installed)"
        return
    fi

    export PGPASSWORD="$POSTGRES_PASSWORD"

    # Test connection
    if psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT 1" &>/dev/null; then
        echo "  ✅ PostgreSQL: ${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB} (connected)"

        # Get table count
        local table_count=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public'" 2>/dev/null | tr -d ' ')
        echo "  📊 Tables: $table_count in public schema"

        # Get manifest injection count (last 24 hours)
        local manifest_count=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c "SELECT COUNT(*) FROM agent_manifest_injections WHERE created_at > NOW() - INTERVAL '24 hours'" 2>/dev/null | tr -d ' ' || echo "0")
        echo "  📊 Manifest Injections (24h): $manifest_count"
    else
        echo "  ❌ PostgreSQL: ${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB} (connection failed)"
        add_issue "PostgreSQL connection failed"
    fi

    unset PGPASSWORD
}

# Function to check intelligence collection
check_intelligence() {
    echo ""
    echo "Intelligence Collection (Last 5 min):"

    # Check if psql is available
    if ! command -v psql &> /dev/null; then
        echo "  ⚠️  Cannot check intelligence (psql not installed)"
        return
    fi

    export PGPASSWORD="$POSTGRES_PASSWORD"

    # Get recent pattern discoveries (if table exists)
    local pattern_count=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c "SELECT COUNT(*) FROM agent_manifest_injections WHERE created_at > NOW() - INTERVAL '5 minutes' AND patterns_count > 0" 2>/dev/null | tr -d ' ' || echo "N/A")

    if [[ "$pattern_count" != "N/A" ]]; then
        echo "  ✅ Pattern Discovery: $pattern_count manifest injections with patterns"

        # Get average query time
        local avg_query_time=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c "SELECT ROUND(AVG(total_query_time_ms)) FROM agent_manifest_injections WHERE created_at > NOW() - INTERVAL '5 minutes'" 2>/dev/null | tr -d ' ' || echo "N/A")

        if [[ "$avg_query_time" != "N/A" && -n "$avg_query_time" ]]; then
            echo "  📊 Avg Query Time: ${avg_query_time}ms"

            # Check if query time is too high
            if [[ $avg_query_time -gt 5000 ]]; then
                echo "  ⚠️  Query Time: ${avg_query_time}ms (target <5000ms)"
                add_issue "Intelligence query time above target (${avg_query_time}ms > 5000ms)"
            fi
        fi
    else
        echo "  ℹ️  Intelligence: No recent data available"
    fi

    unset PGPASSWORD
}

# Function to check router service
check_router() {
    echo ""
    echo "Router Service:"

    # Check HTTP health endpoint
    local router_host="${ROUTER_HOST:-localhost}"
    local router_port="${ROUTER_PORT:-8070}"
    local health_response=$(curl -s "http://${router_host}:${router_port}/health" 2>/dev/null || echo "")

    if [[ -n "$health_response" ]]; then
        local status=$(echo "$health_response" | jq -r '.status' 2>/dev/null || echo "unknown")
        echo "  ✅ Router Service: http://${router_host}:${router_port} (${status})"
    else
        echo "  ❌ Router Service: http://${router_host}:${router_port} (connection failed)"
        add_issue "Router service health check failed"
    fi

    # Check recent routing decisions (if psql available)
    if command -v psql &> /dev/null; then
        export PGPASSWORD="$POSTGRES_PASSWORD"

        # Get recent routing decisions count
        local routing_count=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c "SELECT COUNT(*) FROM agent_routing_decisions WHERE created_at > NOW() - INTERVAL '5 minutes'" 2>/dev/null | tr -d ' ' || echo "0")

        if [[ "$routing_count" != "0" && "$routing_count" != "N/A" ]]; then
            echo "  📊 Recent Routing Decisions (5 min): $routing_count"

            # Get average routing time
            local avg_routing_time=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c "SELECT ROUND(AVG(routing_time_ms)) FROM agent_routing_decisions WHERE created_at > NOW() - INTERVAL '5 minutes'" 2>/dev/null | tr -d ' ' || echo "N/A")

            if [[ "$avg_routing_time" != "N/A" && -n "$avg_routing_time" ]]; then
                echo "  📊 Avg Routing Time: ${avg_routing_time}ms"

                # Check if routing time is too high
                if [[ $avg_routing_time -gt 100 ]]; then
                    echo "  ⚠️  Routing Time: ${avg_routing_time}ms (target <100ms)"
                    add_issue "Router avg time above target (${avg_routing_time}ms > 100ms)"
                fi
            fi

            # Get average confidence score
            local avg_confidence=$(psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c "SELECT ROUND(AVG(confidence_score) * 100) FROM agent_routing_decisions WHERE created_at > NOW() - INTERVAL '5 minutes'" 2>/dev/null | tr -d ' ' || echo "N/A")

            if [[ "$avg_confidence" != "N/A" && -n "$avg_confidence" ]]; then
                echo "  📊 Avg Confidence: ${avg_confidence}%"

                # Check if confidence is too low
                if [[ $avg_confidence -lt 70 ]]; then
                    echo "  ⚠️  Confidence: ${avg_confidence}% (target >70%)"
                    add_issue "Router avg confidence below target (${avg_confidence}% < 70%)"
                fi
            fi
        else
            echo "  ℹ️  No recent routing decisions"
        fi

        unset PGPASSWORD
    fi
}

# Main execution
{
    echo "=== System Health Check ==="
    echo "Timestamp: $TIMESTAMP"
    echo ""
    echo "Services:"

    # Check Archon services
    check_service "archon-intelligence"
    check_service "archon-qdrant"
    check_service "archon-bridge"
    check_service "archon-search"
    check_service "archon-memgraph"
    check_service "archon-kafka-consumer"
    check_service "archon-server"
    check_service "archon-router"

    # Check Omninode services (if they exist)
    if docker ps --filter "name=omninode-" --format "{{.Names}}" | grep -q "omninode-"; then
        echo ""
        echo "Omninode Services:"
        for service in $(docker ps --filter "name=omninode-" --format "{{.Names}}"); do
            check_service "$service"
        done
    fi

    echo ""
    echo "Infrastructure:"

    check_kafka
    check_qdrant
    check_postgres
    check_intelligence
    check_router

    echo ""
    echo "=== Summary ==="

    if [[ $ISSUES_FOUND -eq 0 ]]; then
        echo "✅ All systems healthy"
    else
        echo "❌ Issues Found: $ISSUES_FOUND"
        echo ""
        for issue in "${ISSUES[@]}"; do
            echo "  - $issue"
        done
    fi

    echo ""
    echo "=== End Health Check ==="
} | tee "$OUTPUT_FILE"

# Append to history log
echo "" >> "$HISTORY_FILE"
cat "$OUTPUT_FILE" >> "$HISTORY_FILE"

# Print summary to stderr for scripting
if [[ $ISSUES_FOUND -eq 0 ]]; then
    exit 0
else
    exit 1
fi
