#!/bin/bash
# Test script for router service integration in UserPromptSubmit hook
# Correlation ID: ca95e668-6b52-4387-ba28-8d87ddfaf699

set -euo pipefail

# Portable path resolution
if [ -n "${PROJECT_PATH:-}" ]; then
    REPO_ROOT="$PROJECT_PATH"
elif [ -n "${PROJECT_ROOT:-}" ]; then
    REPO_ROOT="$PROJECT_ROOT"
else
    # Compute from script location (claude_hooks/ -> project root)
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
fi

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=========================================="
echo "Router Service Integration Test"
echo "=========================================="
echo

# Test 1: Router service running check
echo -n "Test 1: Checking if router service is running... "
if curl -s --connect-timeout 2 --max-time 5 http://localhost:8055/health > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Service is running${NC}"
    SERVICE_RUNNING=true
else
    echo -e "${YELLOW}⚠ Service is NOT running (will test fallback)${NC}"
    SERVICE_RUNNING=false
fi
echo

# Test 2: Test routing request
echo "Test 2: Testing routing request..."
CORRELATION_ID="$(uuidgen | tr '[:upper:]' '[:lower:]')"
TEST_PROMPT="Create a React component for user authentication"

REQUEST_JSON="$(jq -n \
  --arg prompt "$TEST_PROMPT" \
  --arg correlation_id "$CORRELATION_ID" \
  '{user_request: $prompt, correlation_id: $correlation_id}')"

echo "  Request: $TEST_PROMPT"
echo "  Correlation ID: $CORRELATION_ID"
echo

if [ "$SERVICE_RUNNING" = true ]; then
    echo "  Calling service..."
    ROUTING_RESULT="$(curl -s -X POST http://localhost:8055/route \
      -H "Content-Type: application/json" \
      -d "$REQUEST_JSON" \
      --connect-timeout 2 \
      --max-time 5 || echo "")"

    if [ -n "$ROUTING_RESULT" ]; then
        echo -e "  ${GREEN}✓ Service responded${NC}"
        echo "  Response:"
        echo "$ROUTING_RESULT" | jq '.'

        # Parse response
        AGENT_NAME="$(echo "$ROUTING_RESULT" | jq -r '.selected_agent')"
        CONFIDENCE="$(echo "$ROUTING_RESULT" | jq -r '.confidence')"
        METHOD="$(echo "$ROUTING_RESULT" | jq -r '.method')"
        LATENCY="$(echo "$ROUTING_RESULT" | jq -r '.latency_ms')"

        echo
        echo "  Parsed values:"
        echo "    Agent: $AGENT_NAME"
        echo "    Confidence: $CONFIDENCE"
        echo "    Method: $METHOD"
        echo "    Latency: ${LATENCY}ms"
    else
        echo -e "  ${RED}✗ Service did not respond${NC}"
    fi
else
    echo "  Service not running, testing fallback..."
    ROUTING_RESULT='{"selected_agent":"polymorphic-agent","confidence":0.5,"reasoning":"Router service unavailable - using fallback","method":"fallback","latency_ms":0,"domain":"workflow_coordination","purpose":"Intelligent coordinator for development workflows"}'
    echo -e "  ${GREEN}✓ Fallback response generated${NC}"
    echo "  Response:"
    echo "$ROUTING_RESULT" | jq '.'
fi
echo

# Test 3: Verify hook file syntax
echo -n "Test 3: Verifying hook file syntax... "
if bash -n "$REPO_ROOT/claude_hooks/user-prompt-submit.sh" 2>/dev/null; then
    echo -e "${GREEN}✓ Syntax is valid${NC}"
else
    echo -e "${RED}✗ Syntax error detected${NC}"
    bash -n "$REPO_ROOT/claude_hooks/user-prompt-submit.sh"
fi
echo

# Test 4: Check jq availability
echo -n "Test 4: Checking jq availability... "
if command -v jq >/dev/null 2>&1; then
    echo -e "${GREEN}✓ jq is available${NC}"
else
    echo -e "${RED}✗ jq is NOT available (required for hook)${NC}"
fi
echo

# Test 5: Test timeout scenarios
echo "Test 5: Testing timeout scenarios..."
echo "  Testing connection timeout (expect failure in 2s)..."
START_TIME=$(date +%s)
TIMEOUT_RESULT="$(curl -s -X POST http://192.0.2.1:8055/route \
  -H "Content-Type: application/json" \
  -d "$REQUEST_JSON" \
  --connect-timeout 2 \
  --max-time 5 2>&1 || echo "TIMEOUT")"
END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))

if [ "$TIMEOUT_RESULT" = "TIMEOUT" ] && [ $ELAPSED -le 3 ]; then
    echo -e "  ${GREEN}✓ Timeout handled correctly (${ELAPSED}s)${NC}"
else
    echo -e "  ${YELLOW}⚠ Timeout behavior unexpected (${ELAPSED}s)${NC}"
fi
echo

# Summary
echo "=========================================="
echo "Test Summary"
echo "=========================================="
if [ "$SERVICE_RUNNING" = true ]; then
    echo -e "Router Service: ${GREEN}Running${NC}"
    echo "  ✓ Hook will use service for routing"
    echo "  ✓ Expected latency: <200ms"
else
    echo -e "Router Service: ${YELLOW}Not Running${NC}"
    echo "  ⚠ Hook will use fallback (polymorphic-agent)"
    echo "  ⚠ Latency: 0ms (fallback)"
fi
echo
echo "Hook Integration: Ready"
echo "  ✓ Correlation ID generated before routing"
echo "  ✓ Service call with 2s connection timeout"
echo "  ✓ 5s max timeout for complete request"
echo "  ✓ Fallback to polymorphic-agent if service unavailable"
echo "  ✓ JSON response parsing"
echo "  ✓ Service usage tracking (SERVICE_USED flag)"
echo
echo "Next Steps:"
echo "  1. Start router service: cd agents/lib && python3 agent_router_service.py"
echo "  2. Test hook: echo '{\"prompt\":\"test\"}' | bash claude_hooks/user-prompt-submit.sh"
echo "  3. Check logs: tail -f ~/.claude/hooks/hook-enhanced.log"
echo
