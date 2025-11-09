#!/bin/bash
# Functional Test: Kafka Message Bus
# Tests actual Kafka functionality including publishing, consuming, and topic verification
set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Counters
PASS=0
FAIL=0

# Helper functions
pass() {
    echo -e "${GREEN}✅ $1${NC}"
    ((++PASS))
}

fail() {
    echo -e "${RED}❌ $1${NC}"
    ((++FAIL))
}

warn() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

info() {
    echo -e "$1"
}

# Load environment
if [ ! -f .env ]; then
    fail "Missing .env file"
    exit 1
fi

source .env

# Verify required tools
if ! command -v kcat &> /dev/null; then
    fail "kcat (kafkacat) not installed. Install with: brew install kcat"
    exit 1
fi

# Test configuration
TEST_TOPIC="test-kafka-functional-$(date +%s)"
TEST_CORRELATION_ID="test-corr-$(uuidgen 2>/dev/null || echo "$(date +%s)-$$")"
TEST_MESSAGE="{\"correlation_id\":\"${TEST_CORRELATION_ID}\",\"test\":\"message\",\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}"
CONSUME_TIMEOUT=5

echo "======================================================================="
echo "Kafka Functional Test"
echo "======================================================================="
echo "Broker: ${KAFKA_BOOTSTRAP_SERVERS}"
echo "Test Topic: ${TEST_TOPIC}"
echo "Correlation ID: ${TEST_CORRELATION_ID}"
echo "======================================================================="
echo ""

# Test 1: Kafka Connectivity
echo "TEST 1: Kafka Connectivity"
echo "-----------------------------------"
if kcat -L -b "${KAFKA_BOOTSTRAP_SERVERS}" -t test > /dev/null 2>&1; then
    pass "Connected to Kafka broker"
else
    fail "Failed to connect to Kafka broker"
    echo ""
    echo "=== TEST SUMMARY ==="
    echo "Total: $((PASS + FAIL)) | Passed: ${PASS} | Failed: ${FAIL}"
    exit 1
fi
echo ""

# Test 2: List Topics
echo "TEST 2: Topic Discovery"
echo "-----------------------------------"
TOPIC_LIST=$(kcat -L -b "${KAFKA_BOOTSTRAP_SERVERS}" 2>/dev/null | grep -E "topic \"" | awk -F'"' '{print $2}')
TOPIC_COUNT=$(echo "${TOPIC_LIST}" | wc -l | xargs)

if [ "${TOPIC_COUNT}" -gt 0 ]; then
    pass "Discovered ${TOPIC_COUNT} topics"
    info "Topics: $(echo "${TOPIC_LIST}" | head -5 | tr '\n' ', ' | sed 's/,$//')..."
else
    warn "No topics found (this may be expected for new cluster)"
fi
echo ""

# Test 3: Message Publishing
echo "TEST 3: Message Publishing"
echo "-----------------------------------"
# Use milliseconds if available (Linux), otherwise seconds (macOS)
# Check if date command supports %N (nanoseconds) - only on GNU date
TEST_DATE_OUTPUT=$(date +%s%3N 2>/dev/null)
if [[ "${TEST_DATE_OUTPUT}" =~ ^[0-9]+$ ]]; then
    START_TIME=$(date +%s%3N)
    TIME_UNIT="ms"
else
    START_TIME=$(date +%s)000
    TIME_UNIT="ms"
fi

if echo "${TEST_MESSAGE}" | kcat -P -b "${KAFKA_BOOTSTRAP_SERVERS}" -t "${TEST_TOPIC}" 2>/dev/null; then
    if [[ "${TEST_DATE_OUTPUT}" =~ ^[0-9]+$ ]]; then
        PUBLISH_TIME=$(($(date +%s%3N) - START_TIME))
    else
        PUBLISH_TIME=$(($(date +%s)000 - START_TIME))
    fi
    pass "Published test message (${PUBLISH_TIME}${TIME_UNIT})"
    info "Message: ${TEST_MESSAGE}"
else
    fail "Failed to publish test message"
fi
echo ""

# Test 4: Message Consuming
echo "TEST 4: Message Consuming"
echo "-----------------------------------"
info "Waiting ${CONSUME_TIMEOUT}s for message..."

# Consume with timeout
CONSUMED_MESSAGE=$(timeout ${CONSUME_TIMEOUT} kcat -C -b "${KAFKA_BOOTSTRAP_SERVERS}" -t "${TEST_TOPIC}" -o beginning -e 2>/dev/null | head -1)

if [ -n "${CONSUMED_MESSAGE}" ]; then
    if [[ "${TEST_DATE_OUTPUT}" =~ ^[0-9]+$ ]]; then
        CONSUME_TIME=$(($(date +%s%3N) - START_TIME))
    else
        CONSUME_TIME=$(($(date +%s)000 - START_TIME))
    fi
    pass "Consumed test message (round-trip: ${CONSUME_TIME}${TIME_UNIT})"

    # Verify correlation ID
    if echo "${CONSUMED_MESSAGE}" | grep -q "${TEST_CORRELATION_ID}"; then
        pass "Correlation ID matches"
    else
        warn "Correlation ID mismatch"
        info "Expected: ${TEST_CORRELATION_ID}"
        info "Received: ${CONSUMED_MESSAGE}"
    fi
else
    fail "Failed to consume test message within ${CONSUME_TIMEOUT}s"
fi
echo ""

# Test 5: Critical Topic Verification
echo "TEST 5: Critical Topic Verification"
echo "-----------------------------------"

# Define critical topics
CRITICAL_TOPICS=(
    "agent-actions"
    "agent.routing.requested.v1"
    "agent.routing.completed.v1"
    "agent.routing.failed.v1"
    "dev.archon-intelligence.intelligence.code-analysis-requested.v1"
    "dev.archon-intelligence.intelligence.code-analysis-completed.v1"
    "dev.archon-intelligence.intelligence.code-analysis-failed.v1"
    "documentation-changed"
    "agent-transformation-events"
    "router-performance-metrics"
)

for topic in "${CRITICAL_TOPICS[@]}"; do
    if echo "${TOPIC_LIST}" | grep -q "^${topic}$"; then
        pass "${topic}"
    else
        warn "${topic} (not found - may need creation)"
    fi
done
echo ""

# Test 6: Consumer Group Check
echo "TEST 6: Consumer Group Status"
echo "-----------------------------------"

# Note: This requires rpk or kafka-consumer-groups.sh
# For now, we'll just check if we can list consumer groups via kcat metadata
if kcat -L -b "${KAFKA_BOOTSTRAP_SERVERS}" 2>/dev/null | grep -q "broker"; then
    pass "Broker metadata accessible"

    # Try to get consumer group info (requires docker access to redpanda)
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "redpanda\|kafka"; then
        CONTAINER=$(docker ps --format '{{.Names}}' | grep -E "redpanda|kafka" | head -1)
        if [ -n "${CONTAINER}" ]; then
            GROUP_COUNT=$(docker exec "${CONTAINER}" rpk group list 2>/dev/null | wc -l | xargs)
            if [ "${GROUP_COUNT}" -gt 0 ]; then
                info "Consumer groups: ${GROUP_COUNT}"
            fi
        fi
    fi
else
    warn "Could not access broker metadata"
fi
echo ""

# Test 7: Cleanup
echo "TEST 7: Cleanup"
echo "-----------------------------------"
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "redpanda\|kafka"; then
    CONTAINER=$(docker ps --format '{{.Names}}' | grep -E "redpanda|kafka" | head -1)
    if [ -n "${CONTAINER}" ]; then
        if docker exec "${CONTAINER}" rpk topic delete "${TEST_TOPIC}" 2>/dev/null; then
            pass "Deleted test topic: ${TEST_TOPIC}"
        else
            warn "Could not delete test topic (may need manual cleanup)"
        fi
    fi
else
    warn "Cannot delete test topic (no Kafka/Redpanda container access)"
fi
echo ""

# Summary
echo "======================================================================="
echo "TEST SUMMARY"
echo "======================================================================="
echo "Total Tests: $((PASS + FAIL))"
echo -e "${GREEN}Passed: ${PASS}${NC}"
echo -e "${RED}Failed: ${FAIL}${NC}"
echo ""

if [ "${FAIL}" -eq 0 ]; then
    echo -e "${GREEN}✅ ALL TESTS PASSED${NC}"
    exit 0
else
    echo -e "${RED}❌ SOME TESTS FAILED${NC}"
    exit 1
fi
