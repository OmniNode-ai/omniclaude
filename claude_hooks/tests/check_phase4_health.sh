#!/bin/bash
# Phase 4 API Health Check Script
#
# Validates Phase 4 Pattern Traceability API is running and responsive.
# Tests all major endpoints for availability and correct responses.

set -e

API_BASE_URL="${API_URL:-http://localhost:8053}"
API_PREFIX="/api/pattern-traceability"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo "======================================================================="
echo "Phase 4 Pattern Traceability - API Health Check"
echo "======================================================================="
echo ""
echo "API Base URL: $API_BASE_URL"
echo "API Prefix: $API_PREFIX"
echo ""

# Check if jq is available
if ! command -v jq &> /dev/null; then
    echo -e "${YELLOW}⚠ jq not installed (optional for pretty JSON output)${NC}"
    JQ_AVAILABLE=false
else
    JQ_AVAILABLE=true
fi

# Check if curl is available
if ! command -v curl &> /dev/null; then
    echo -e "${RED}✗ curl not found${NC}"
    echo "  Please install curl to run health checks"
    exit 1
fi

# Test counter
TESTS_PASSED=0
TESTS_FAILED=0

# Function to test endpoint
test_endpoint() {
    local method=$1
    local endpoint=$2
    local description=$3
    local data=$4

    echo "-----------------------------------------------------------------------"
    echo "Testing: $description"
    echo "  $method $endpoint"
    echo "-----------------------------------------------------------------------"

    # Build curl command
    local curl_cmd="curl -s -w '\n%{http_code}' -X $method"

    if [ -n "$data" ]; then
        curl_cmd="$curl_cmd -H 'Content-Type: application/json' -d '$data'"
    fi

    curl_cmd="$curl_cmd $API_BASE_URL$endpoint"

    # Execute request
    local response=$(eval $curl_cmd)
    local http_code=$(echo "$response" | tail -n1)
    local body=$(echo "$response" | sed '$d')

    # Check status code
    if [ "$http_code" == "200" ] || [ "$http_code" == "201" ]; then
        echo -e "${GREEN}✓ HTTP $http_code${NC}"

        # Pretty print JSON if jq is available
        if [ "$JQ_AVAILABLE" = true ] && echo "$body" | jq . &> /dev/null; then
            echo ""
            echo "$body" | jq '.'
        else
            echo "$body"
        fi

        echo ""
        TESTS_PASSED=$((TESTS_PASSED + 1))
        return 0
    else
        echo -e "${RED}✗ HTTP $http_code${NC}"
        echo ""
        echo "Response:"
        echo "$body"
        echo ""
        TESTS_FAILED=$((TESTS_FAILED + 1))
        return 1
    fi
}

# ============================================================================
# Test 1: Health Endpoint
# ============================================================================

echo ""
test_endpoint \
    "GET" \
    "/health" \
    "Service Health Check"

# ============================================================================
# Test 2: Phase 4 Health Endpoint
# ============================================================================

echo ""
test_endpoint \
    "GET" \
    "$API_PREFIX/health" \
    "Phase 4 Component Health"

# ============================================================================
# Test 3: Track Lineage (requires database)
# ============================================================================

echo ""
TEST_PATTERN_ID="test$(date +%s)abc"
TEST_DATA='{
    "event_type": "pattern_created",
    "pattern_id": "'$TEST_PATTERN_ID'",
    "pattern_name": "health_check_test",
    "pattern_type": "code",
    "pattern_version": "1.0.0",
    "pattern_data": {
        "code": "def test(): pass",
        "language": "python"
    },
    "triggered_by": "health-check"
}'

if test_endpoint \
    "POST" \
    "$API_PREFIX/lineage/track" \
    "Track Pattern Lineage" \
    "$TEST_DATA"; then
    echo -e "${BLUE}ℹ Lineage tracking is operational${NC}"
    echo ""
else
    echo -e "${YELLOW}⚠ Lineage tracking may be disabled (database unavailable)${NC}"
    echo ""
fi

# ============================================================================
# Test 4: Query Lineage
# ============================================================================

echo ""
if test_endpoint \
    "GET" \
    "$API_PREFIX/lineage/$TEST_PATTERN_ID?include_ancestors=true&include_descendants=true" \
    "Query Pattern Lineage"; then
    echo -e "${BLUE}ℹ Lineage query is operational${NC}"
    echo ""
else
    echo -e "${YELLOW}⚠ Lineage query failed (pattern may not exist)${NC}"
    echo ""
fi

# ============================================================================
# Test 5: Compute Analytics
# ============================================================================

echo ""
ANALYTICS_DATA='{
    "pattern_id": "'$TEST_PATTERN_ID'",
    "time_window_type": "daily",
    "include_performance": true,
    "include_trends": true
}'

if test_endpoint \
    "POST" \
    "$API_PREFIX/analytics/compute" \
    "Compute Pattern Analytics" \
    "$ANALYTICS_DATA"; then
    echo -e "${BLUE}ℹ Analytics computation is operational${NC}"
    echo ""
else
    echo -e "${YELLOW}⚠ Analytics computation may have insufficient data${NC}"
    echo ""
fi

# ============================================================================
# Test 6: Search Patterns
# ============================================================================

echo ""
SEARCH_DATA='{
    "query": "test",
    "limit": 5
}'

if test_endpoint \
    "POST" \
    "$API_PREFIX/search" \
    "Search Patterns" \
    "$SEARCH_DATA"; then
    echo -e "${BLUE}ℹ Pattern search is operational${NC}"
    echo ""
else
    echo -e "${YELLOW}⚠ Pattern search failed${NC}"
    echo ""
fi

# ============================================================================
# Summary
# ============================================================================

echo "======================================================================="
echo "Health Check Summary"
echo "======================================================================="
echo ""
echo -e "Tests Passed: ${GREEN}$TESTS_PASSED${NC}"
echo -e "Tests Failed: ${RED}$TESTS_FAILED${NC}"
echo ""

if [ $TESTS_FAILED -eq 0 ]; then
    echo -e "${GREEN}✓ All health checks passed${NC}"
    echo ""
    echo "Phase 4 API Status: HEALTHY"
    echo ""
    exit 0
elif [ $TESTS_PASSED -gt 0 ]; then
    echo -e "${YELLOW}⚠ Some health checks failed${NC}"
    echo ""
    echo "Phase 4 API Status: DEGRADED"
    echo "  • Some features may be unavailable"
    echo "  • Check database connection if lineage tracking failed"
    echo ""
    exit 1
else
    echo -e "${RED}✗ All health checks failed${NC}"
    echo ""
    echo "Phase 4 API Status: UNHEALTHY"
    echo "  • Service may not be running"
    echo "  • Check that Intelligence Service is running on $API_BASE_URL"
    echo ""
    exit 2
fi
