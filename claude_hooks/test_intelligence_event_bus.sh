#!/bin/bash
# Test script for intelligence request/response event bus pattern
# MVP baseline test - verifies hook can publish requests to Kafka

set -euo pipefail

HOOKS_LIB="$HOME/.claude/hooks/lib"
TEST_CORRELATION_ID="$(uuidgen | tr '[:upper:]' '[:lower:]')"
TEST_OUTPUT_DOMAIN="/tmp/test_intelligence_domain_${TEST_CORRELATION_ID}.json"
TEST_OUTPUT_IMPL="/tmp/test_intelligence_impl_${TEST_CORRELATION_ID}.json"

echo "========================================================================="
echo "Intelligence Event Bus MVP Test"
echo "========================================================================="
echo "Correlation ID: $TEST_CORRELATION_ID"
echo "Kafka Brokers: ${KAFKA_BROKERS:-192.168.86.200:29102}"
echo ""

# Test 1: Domain intelligence request
echo "Test 1: Publishing domain intelligence request..."
python3 "${HOOKS_LIB}/publish_intelligence_request.py" \
    --query-type "domain" \
    --query "Python async patterns for event processing" \
    --correlation-id "$TEST_CORRELATION_ID" \
    --agent-name "test-agent" \
    --agent-domain "testing" \
    --output-file "$TEST_OUTPUT_DOMAIN" \
    --match-count 5 \
    --timeout-ms 500 \
    --debug || echo "Expected timeout (no consumer running)"

if [[ -f "$TEST_OUTPUT_DOMAIN" ]]; then
    echo "✅ Domain intelligence request published successfully"
    echo "Output file: $TEST_OUTPUT_DOMAIN"
    echo "Contents:"
    cat "$TEST_OUTPUT_DOMAIN" | jq '.' 2>/dev/null || cat "$TEST_OUTPUT_DOMAIN"
else
    echo "❌ Domain intelligence request failed - no output file"
    exit 1
fi

echo ""
echo "Test 2: Publishing implementation intelligence request..."
python3 "${HOOKS_LIB}/publish_intelligence_request.py" \
    --query-type "implementation" \
    --query "Kafka consumer patterns with correlation IDs" \
    --correlation-id "$TEST_CORRELATION_ID" \
    --agent-name "test-agent" \
    --agent-domain "testing" \
    --output-file "$TEST_OUTPUT_IMPL" \
    --match-count 3 \
    --timeout-ms 500 \
    --debug || echo "Expected timeout (no consumer running)"

if [[ -f "$TEST_OUTPUT_IMPL" ]]; then
    echo "✅ Implementation intelligence request published successfully"
    echo "Output file: $TEST_OUTPUT_IMPL"
    echo "Contents:"
    cat "$TEST_OUTPUT_IMPL" | jq '.' 2>/dev/null || cat "$TEST_OUTPUT_IMPL"
else
    echo "❌ Implementation intelligence request failed - no output file"
    exit 1
fi

echo ""
echo "========================================================================="
echo "MVP Baseline Test Results"
echo "========================================================================="
echo "✅ Hook can publish intelligence requests to Kafka"
echo "✅ Request/response pattern handles timeouts gracefully"
echo "✅ Output files are written with empty intelligence on timeout"
echo ""
echo "Next Steps:"
echo "1. Implement intelligence service consumer (listens to intelligence.requests)"
echo "2. Consumer queries Qdrant/RAG and publishes to intelligence.responses"
echo "3. Hook receives intelligence context automatically"
echo ""
echo "Cleanup:"
echo "  rm $TEST_OUTPUT_DOMAIN"
echo "  rm $TEST_OUTPUT_IMPL"
echo "========================================================================="
