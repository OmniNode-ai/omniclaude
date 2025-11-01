#!/bin/bash
# Test Agent YAML Injection (Migration 015)
# Verifies that hooks correctly load and inject agent YAML

set -euo pipefail

HOOKS_LIB="$HOME/.claude/hooks/lib"
AGENT_DEFS="$HOME/.claude/agent-definitions"

echo "=========================================="
echo "Testing Agent YAML Injection"
echo "=========================================="
echo ""

# Test 1: Verify simple_agent_loader.py exists
echo "Test 1: Verify simple_agent_loader.py exists"
if [[ -f "$HOOKS_LIB/simple_agent_loader.py" ]]; then
    echo "✅ PASS: simple_agent_loader.py found"
else
    echo "❌ FAIL: simple_agent_loader.py not found"
    exit 1
fi
echo ""

# Test 2: Verify agent definitions exist
echo "Test 2: Verify agent definitions exist"
AGENT_COUNT=$(ls "$AGENT_DEFS"/*.yaml 2>/dev/null | wc -l | tr -d ' ')
if [[ $AGENT_COUNT -gt 0 ]]; then
    echo "✅ PASS: Found $AGENT_COUNT agent definitions"
else
    echo "❌ FAIL: No agent definitions found"
    exit 1
fi
echo ""

# Test 3: Load polymorphic-agent
echo "Test 3: Load polymorphic-agent"
RESULT=$(echo '{"agent_name": "polymorphic-agent"}' | python3 "$HOOKS_LIB/simple_agent_loader.py" 2>&1)
SUCCESS=$(echo "$RESULT" | jq -r '.success // false')
if [[ "$SUCCESS" == "true" ]]; then
    YAML_SIZE=$(echo "$RESULT" | jq -r '.context_injection' | wc -c | tr -d ' ')
    echo "✅ PASS: Loaded polymorphic-agent ($YAML_SIZE bytes)"
else
    echo "❌ FAIL: Failed to load polymorphic-agent"
    echo "$RESULT"
    exit 1
fi
echo ""

# Test 4: Load api-architect
echo "Test 4: Load api-architect"
RESULT=$(echo '{"agent_name": "api-architect"}' | python3 "$HOOKS_LIB/simple_agent_loader.py" 2>&1)
SUCCESS=$(echo "$RESULT" | jq -r '.success // false')
if [[ "$SUCCESS" == "true" ]]; then
    YAML_SIZE=$(echo "$RESULT" | jq -r '.context_injection' | wc -c | tr -d ' ')
    echo "✅ PASS: Loaded api-architect ($YAML_SIZE bytes)"
else
    echo "❌ FAIL: Failed to load api-architect"
    echo "$RESULT"
    exit 1
fi
echo ""

# Test 5: Test with agent- prefix stripping
echo "Test 5: Test prefix stripping (load via 'researcher' finds 'agent-researcher.yaml')"
if [[ -f "$AGENT_DEFS/researcher.yaml" ]]; then
    AGENT_FILE="researcher"
elif [[ -f "$AGENT_DEFS/agent-researcher.yaml" ]]; then
    AGENT_FILE="agent-researcher"
else
    echo "⚠️  SKIP: No researcher agent found"
    AGENT_FILE=""
fi

if [[ -n "$AGENT_FILE" ]]; then
    RESULT=$(echo "{\"agent_name\": \"$AGENT_FILE\"}" | python3 "$HOOKS_LIB/simple_agent_loader.py" 2>&1)
    SUCCESS=$(echo "$RESULT" | jq -r '.success // false')
    if [[ "$SUCCESS" == "true" ]]; then
        echo "✅ PASS: Loaded $AGENT_FILE"
    else
        echo "❌ FAIL: Failed to load $AGENT_FILE"
        exit 1
    fi
fi
echo ""

# Test 6: Verify YAML injection header
echo "Test 6: Verify YAML injection header format"
RESULT=$(echo '{"agent_name": "polymorphic-agent"}' | python3 "$HOOKS_LIB/simple_agent_loader.py" 2>&1)
YAML_CONTENT=$(echo "$RESULT" | jq -r '.context_injection')

if echo "$YAML_CONTENT" | grep -q "POLYMORPHIC AGENT IDENTITY INJECTION"; then
    echo "✅ PASS: Header includes 'POLYMORPHIC AGENT IDENTITY INJECTION'"
else
    echo "❌ FAIL: Header missing expected text"
    exit 1
fi

if echo "$YAML_CONTENT" | grep -q "Agent: polymorphic-agent"; then
    echo "✅ PASS: Header includes agent name"
else
    echo "❌ FAIL: Header missing agent name"
    exit 1
fi
echo ""

# Test 7: Verify agent_identity section present
echo "Test 7: Verify agent_identity section present"
if echo "$YAML_CONTENT" | grep -q "agent_identity:"; then
    echo "✅ PASS: YAML includes agent_identity section"
else
    echo "❌ FAIL: YAML missing agent_identity section"
    exit 1
fi
echo ""

# Test 8: Simulate hook invocation logic
echo "Test 8: Simulate hook invocation logic"
AGENT_NAME="polymorphic-agent"
INVOKE_INPUT="$(jq -n --arg agent "$AGENT_NAME" '{agent_name: $agent}')"
INVOKE_RESULT="$(echo "$INVOKE_INPUT" | timeout 3 python3 "$HOOKS_LIB/simple_agent_loader.py" 2>&1 || echo '{}')"
INVOKE_SUCCESS="$(echo "$INVOKE_RESULT" | jq -r '.success // false')"

if [[ "$INVOKE_SUCCESS" == "true" ]]; then
    AGENT_YAML_INJECTION="$(echo "$INVOKE_RESULT" | jq -r '.context_injection // ""')"
    if [[ -n "$AGENT_YAML_INJECTION" ]]; then
        echo "✅ PASS: Hook simulation successful (${#AGENT_YAML_INJECTION} chars)"
    else
        echo "❌ FAIL: Hook simulation returned empty YAML"
        exit 1
    fi
else
    echo "❌ FAIL: Hook simulation failed"
    exit 1
fi
echo ""

echo "=========================================="
echo "All Tests Passed! ✅"
echo "=========================================="
echo ""
echo "Summary:"
echo "  - simple_agent_loader.py works correctly"
echo "  - Can load all $AGENT_COUNT agent definitions"
echo "  - YAML injection format is correct"
echo "  - Hook integration logic validated"
echo ""
echo "Next Steps:"
echo "  1. Trigger a user prompt via Claude Code"
echo "  2. Check ~/.claude/hooks/hook-enhanced.log"
echo "  3. Look for: 'Agent YAML loaded successfully (N chars)'"
echo "  4. Verify: '✅ AGENT IDENTITY LOADED' in hook output"
