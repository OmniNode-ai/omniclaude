#!/bin/bash
# Stream 3 Completion Verification
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
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "=========================================="
echo "Stream 3: Hook Integration - Verification"
echo "=========================================="
echo

PASSED=0
FAILED=0
WARNINGS=0

# Check 1: Hook file exists and is valid
echo -n "1. Hook file exists and is valid... "
if [ -f "$REPO_ROOT/claude_hooks/user-prompt-submit.sh" ]; then
    if bash -n "$REPO_ROOT/claude_hooks/user-prompt-submit.sh" 2>/dev/null; then
        echo -e "${GREEN}✓ PASS${NC}"
        PASSED=$((PASSED + 1))
    else
        echo -e "${RED}✗ FAIL - Syntax error${NC}"
        FAILED=$((FAILED + 1))
    fi
else
    echo -e "${RED}✗ FAIL - File not found${NC}"
    FAILED=$((FAILED + 1))
fi

# Check 2: Correlation ID generated before agent detection
echo -n "2. Correlation ID before agent detection... "
CORR_LINE=$(grep -n "Correlation ID (generated before agent detection)" $REPO_ROOT/claude_hooks/user-prompt-submit.sh | cut -d: -f1)
AGENT_LINE=$(grep -n "Agent detection via Router Service" $REPO_ROOT/claude_hooks/user-prompt-submit.sh | cut -d: -f1)

if [ "$CORR_LINE" -lt "$AGENT_LINE" ]; then
    echo -e "${GREEN}✓ PASS${NC} (line $CORR_LINE < line $AGENT_LINE)"
    PASSED=$((PASSED + 1))
else
    echo -e "${RED}✗ FAIL${NC} (line $CORR_LINE >= line $AGENT_LINE)"
    FAILED=$((FAILED + 1))
fi

# Check 3: curl command with proper timeouts
echo -n "3. curl command with timeouts... "
if grep -q "curl -s -X POST http://localhost:8055/route" $REPO_ROOT/claude_hooks/user-prompt-submit.sh && \
   grep -q "\-\-connect-timeout 2" $REPO_ROOT/claude_hooks/user-prompt-submit.sh && \
   grep -q "\-\-max-time 5" $REPO_ROOT/claude_hooks/user-prompt-submit.sh; then
    echo -e "${GREEN}✓ PASS${NC}"
    PASSED=$((PASSED + 1))
else
    echo -e "${RED}✗ FAIL - Missing timeout parameters${NC}"
    FAILED=$((FAILED + 1))
fi

# Check 4: Fallback logic present
echo -n "4. Fallback logic present... "
if grep -q "Router service unavailable - using fallback" $REPO_ROOT/claude_hooks/user-prompt-submit.sh && \
   grep -q "SERVICE_USED=\"false\"" $REPO_ROOT/claude_hooks/user-prompt-submit.sh; then
    echo -e "${GREEN}✓ PASS${NC}"
    PASSED=$((PASSED + 1))
else
    echo -e "${RED}✗ FAIL - Missing fallback logic${NC}"
    FAILED=$((FAILED + 1))
fi

# Check 5: JSON response parsing with defaults
echo -n "5. JSON response parsing with defaults... "
if grep -q "jq -r '.selected_agent // \"NO_AGENT_DETECTED\"'" $REPO_ROOT/claude_hooks/user-prompt-submit.sh && \
   grep -q "jq -r '.confidence // \"0.5\"'" $REPO_ROOT/claude_hooks/user-prompt-submit.sh; then
    echo -e "${GREEN}✓ PASS${NC}"
    PASSED=$((PASSED + 1))
else
    echo -e "${RED}✗ FAIL - Missing default values in jq parsing${NC}"
    FAILED=$((FAILED + 1))
fi

# Check 6: Service usage tracking
echo -n "6. Service usage tracking... "
if grep -q "service=\${SERVICE_USED}" $REPO_ROOT/claude_hooks/user-prompt-submit.sh; then
    echo -e "${GREEN}✓ PASS${NC}"
    PASSED=$((PASSED + 1))
else
    echo -e "${RED}✗ FAIL - Missing SERVICE_USED tracking${NC}"
    FAILED=$((FAILED + 1))
fi

# Check 7: No duplicate correlation ID generation
echo -n "7. No duplicate correlation ID generation... "
CORR_COUNT=$(grep -c "Correlation ID" $REPO_ROOT/claude_hooks/user-prompt-submit.sh | grep -v "Correlation ID:" || echo "1")
if [ "$CORR_COUNT" -eq "1" ]; then
    echo -e "${GREEN}✓ PASS${NC} (single generation)"
    PASSED=$((PASSED + 1))
else
    echo -e "${YELLOW}⚠ WARNING${NC} (found $CORR_COUNT instances - verify no duplicates)"
    WARNINGS=$((WARNINGS + 1))
fi

# Check 8: Test script exists and is executable
echo -n "8. Test script exists and is executable... "
if [ -f "$REPO_ROOT/claude_hooks/test_router_service_integration.sh" ] && \
   [ -x "$REPO_ROOT/claude_hooks/test_router_service_integration.sh" ]; then
    echo -e "${GREEN}✓ PASS${NC}"
    PASSED=$((PASSED + 1))
else
    echo -e "${RED}✗ FAIL - Test script missing or not executable${NC}"
    FAILED=$((FAILED + 1))
fi

# Check 9: Documentation exists
echo -n "9. Documentation exists... "
if [ -f "$REPO_ROOT/docs/HOOK_ROUTER_SERVICE_INTEGRATION.md" ]; then
    echo -e "${GREEN}✓ PASS${NC}"
    PASSED=$((PASSED + 1))
else
    echo -e "${RED}✗ FAIL - Documentation not found${NC}"
    FAILED=$((FAILED + 1))
fi

# Check 10: jq dependency available
echo -n "10. jq dependency available... "
if command -v jq >/dev/null 2>&1; then
    echo -e "${GREEN}✓ PASS${NC}"
    PASSED=$((PASSED + 1))
else
    echo -e "${RED}✗ FAIL - jq not installed${NC}"
    FAILED=$((FAILED + 1))
fi

# Check 11: curl dependency available
echo -n "11. curl dependency available... "
if command -v curl >/dev/null 2>&1; then
    echo -e "${GREEN}✓ PASS${NC}"
    PASSED=$((PASSED + 1))
else
    echo -e "${RED}✗ FAIL - curl not installed${NC}"
    FAILED=$((FAILED + 1))
fi

# Check 12: Router service endpoint (warning if not available)
echo -n "12. Router service endpoint... "
if curl -s --connect-timeout 2 --max-time 5 http://localhost:8055/health >/dev/null 2>&1; then
    echo -e "${GREEN}✓ PASS${NC} (service running)"
    PASSED=$((PASSED + 1))
else
    echo -e "${YELLOW}⚠ WARNING${NC} (service not running - fallback will be used)"
    WARNINGS=$((WARNINGS + 1))
fi

echo
echo "=========================================="
echo "Verification Summary"
echo "=========================================="
echo -e "Passed:   ${GREEN}${PASSED}/12${NC}"
echo -e "Failed:   ${RED}${FAILED}/12${NC}"
echo -e "Warnings: ${YELLOW}${WARNINGS}/12${NC}"
echo

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✓ Stream 3 is COMPLETE and READY FOR INTEGRATION${NC}"
    echo
    echo "Next steps:"
    echo "  1. Stream 1: Implement /route endpoint in router service"
    echo "  2. Integration: End-to-end testing with real prompts"
    echo "  3. Monitoring: Set up service health alerts"
    exit 0
else
    echo -e "${RED}✗ Stream 3 has FAILED checks - review required${NC}"
    exit 1
fi
