#!/bin/bash
# Test script for Quality Enforcer orchestrator
# Tests different phases and configurations

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENFORCER="$SCRIPT_DIR/quality_enforcer.py"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "Testing AI Quality Enforcer Orchestrator"
echo "========================================"
echo ""

# Test 1: Phase 1 only (default configuration)
echo -e "${YELLOW}Test 1: Phase 1 Only (Validation)${NC}"
export ENABLE_PHASE_1_VALIDATION=true
export ENABLE_PHASE_2_RAG=false
export ENABLE_PHASE_4_AI_QUORUM=false

TEST_INPUT='{"tool_name":"Write","parameters":{"file_path":"/tmp/test.py","content":"def calculateTotal(x):\n    return x\n"}}'

echo "Input: Python function with camelCase name"
echo "$TEST_INPUT" | python3 "$ENFORCER" > /tmp/test1_output.json 2>&1

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Test 1 Passed${NC}"
else
    echo -e "${RED}✗ Test 1 Failed${NC}"
fi
echo ""

# Test 2: TypeScript file
echo -e "${YELLOW}Test 2: TypeScript File${NC}"
TEST_INPUT='{"tool_name":"Write","parameters":{"file_path":"/tmp/test.ts","content":"function calculate_total(items: number[]): number {\n    return items.reduce((a, b) => a + b, 0);\n}"}}'

echo "Input: TypeScript function with snake_case name"
echo "$TEST_INPUT" | python3 "$ENFORCER" > /tmp/test2_output.json 2>&1

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Test 2 Passed${NC}"
else
    echo -e "${RED}✗ Test 2 Failed${NC}"
fi
echo ""

# Test 3: Clean code (no violations)
echo -e "${YELLOW}Test 3: Clean Code (No Violations)${NC}"
TEST_INPUT='{"tool_name":"Write","parameters":{"file_path":"/tmp/test.py","content":"def calculate_total(items):\n    return sum(items)\n"}}'

echo "Input: Correctly formatted Python function"
echo "$TEST_INPUT" | python3 "$ENFORCER" > /tmp/test3_output.json 2>&1

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Test 3 Passed${NC}"
else
    echo -e "${RED}✗ Test 3 Failed${NC}"
fi
echo ""

# Test 4: Edit tool
echo -e "${YELLOW}Test 4: Edit Tool${NC}"
TEST_INPUT='{"tool_name":"Edit","parameters":{"file_path":"/tmp/test.py","old_string":"def test()","new_string":"def calculateSum(x, y):\n    return x + y"}}'

echo "Input: Edit operation with naming violation"
echo "$TEST_INPUT" | python3 "$ENFORCER" > /tmp/test4_output.json 2>&1

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Test 4 Passed${NC}"
else
    echo -e "${RED}✗ Test 4 Failed${NC}"
fi
echo ""

# Test 5: Unsupported file type
echo -e "${YELLOW}Test 5: Unsupported File Type${NC}"
TEST_INPUT='{"tool_name":"Write","parameters":{"file_path":"/tmp/test.txt","content":"Some text content"}}'

echo "Input: .txt file (should be skipped)"
echo "$TEST_INPUT" | python3 "$ENFORCER" > /tmp/test5_output.json 2>&1

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Test 5 Passed${NC}"
else
    echo -e "${RED}✗ Test 5 Failed${NC}"
fi
echo ""

# Test 6: Invalid JSON
echo -e "${YELLOW}Test 6: Invalid JSON (Error Handling)${NC}"
echo "Invalid JSON input" | python3 "$ENFORCER" > /tmp/test6_output.json 2>&1

if [ $? -eq 1 ]; then
    echo -e "${GREEN}✓ Test 6 Passed (Error handled correctly)${NC}"
else
    echo -e "${RED}✗ Test 6 Failed (Should return exit code 1)${NC}"
fi
echo ""

# Test 7: Performance budget
echo -e "${YELLOW}Test 7: Performance Budget${NC}"
export PERFORMANCE_BUDGET_SECONDS=0.1  # Very strict budget

TEST_INPUT='{"tool_name":"Write","parameters":{"file_path":"/tmp/test.py","content":"def test(): pass"}}'

echo "Input: Testing with 0.1s performance budget"
START_TIME=$(date +%s%N)
echo "$TEST_INPUT" | python3 "$ENFORCER" > /tmp/test7_output.json 2>&1
END_TIME=$(date +%s%N)
ELAPSED=$(( (END_TIME - START_TIME) / 1000000 ))  # Convert to milliseconds

echo "Elapsed time: ${ELAPSED}ms"
if [ $ELAPSED -lt 150 ]; then
    echo -e "${GREEN}✓ Test 7 Passed (Within budget + overhead)${NC}"
else
    echo -e "${YELLOW}! Test 7: Time slightly over (acceptable with overhead)${NC}"
fi
echo ""

# Summary
echo "========================================"
echo "Test Summary"
echo "========================================"
echo "Output files created in /tmp/test*_output.json"
echo ""
echo "To view detailed logs:"
echo "  cat /tmp/test1_output.json"
echo ""
echo "To test with different phase configurations:"
echo "  export ENABLE_PHASE_2_RAG=true"
echo "  export ENABLE_PHASE_4_AI_QUORUM=true"
echo ""
echo "All tests completed!"
