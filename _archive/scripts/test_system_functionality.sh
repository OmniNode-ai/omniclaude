#!/bin/bash
# Master Functional Test Runner
# Tests actual system functionality, not just container names

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  SYSTEM FUNCTIONAL TEST SUITE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Testing actual system functionality (not just container names)"
echo "Timestamp: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# Source environment
if [ -f .env ]; then
    source .env
    echo -e "${GREEN}✓${NC} Environment loaded"
else
    echo -e "${RED}✗${NC} .env file not found"
    exit 2
fi

echo ""

# Test results
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

run_test() {
    local test_name=$1
    local test_script=$2

    TOTAL_TESTS=$((TOTAL_TESTS + 1))

    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "TEST $TOTAL_TESTS: $test_name"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    if bash "$test_script"; then
        echo -e "${GREEN}✓ PASSED${NC}: $test_name"
        PASSED_TESTS=$((PASSED_TESTS + 1))
        echo ""
        return 0
    else
        echo -e "${RED}✗ FAILED${NC}: $test_name"
        FAILED_TESTS=$((FAILED_TESTS + 1))
        echo ""
        return 1
    fi
}

# Run all tests
run_test "Kafka Message Bus" "scripts/tests/test_kafka_functionality.sh" || true
run_test "PostgreSQL Database" "scripts/tests/test_postgres_functionality.sh" || true
run_test "Intelligence Integration" "scripts/tests/test_intelligence_functionality.sh" || true
run_test "Agent Routing" "scripts/tests/test_routing_functionality.sh" || true

# Summary
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  TEST SUMMARY"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Total Tests:   $TOTAL_TESTS"
echo -e "${GREEN}Passed:${NC}        $PASSED_TESTS"
if [ $FAILED_TESTS -gt 0 ]; then
    echo -e "${RED}Failed:${NC}        $FAILED_TESTS"
fi
echo ""

# Health score
HEALTH_SCORE=$((PASSED_TESTS * 100 / TOTAL_TESTS))
echo -e "System Health: ${HEALTH_SCORE}%"
echo ""

# Exit code
if [ $FAILED_TESTS -eq 0 ]; then
    echo -e "${GREEN}✓ All functional tests passed!${NC}"
    exit 0
else
    echo -e "${YELLOW}⚠ Some tests failed. Check logs above.${NC}"
    exit 1
fi
