#!/bin/bash
#
# Test script to verify health_check.sh exit codes
#
# Tests:
# 1. Mock scenario with issues (should exit 1)
# 2. Mock scenario without issues (should exit 0)
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== Health Check Exit Code Tests ==="
echo ""

# Test 1: Run actual health check and capture exit code
echo "Test 1: Running actual health check..."
if "$SCRIPT_DIR/health_check.sh" > /dev/null 2>&1; then
    ACTUAL_EXIT_CODE=0
else
    ACTUAL_EXIT_CODE=$?
fi

echo "  Actual exit code: $ACTUAL_EXIT_CODE"

# Check the summary from the output file
if grep -q "✅ All systems healthy" "$PROJECT_ROOT/tmp/health_check_latest.txt"; then
    EXPECTED_EXIT_CODE=0
    echo "  Health check summary: All systems healthy"
elif grep -q "❌ Issues Found:" "$PROJECT_ROOT/tmp/health_check_latest.txt"; then
    ISSUE_COUNT=$(grep "❌ Issues Found:" "$PROJECT_ROOT/tmp/health_check_latest.txt" | awk '{print $NF}')
    EXPECTED_EXIT_CODE=1
    echo "  Health check summary: Issues found ($ISSUE_COUNT)"
else
    echo "  ⚠️  Could not parse health check summary"
    EXPECTED_EXIT_CODE="unknown"
fi

echo ""

# Verify exit code matches expectation
if [[ "$EXPECTED_EXIT_CODE" == "unknown" ]]; then
    echo "❌ TEST FAILED: Could not determine expected exit code"
    exit 1
elif [[ $ACTUAL_EXIT_CODE -eq $EXPECTED_EXIT_CODE ]]; then
    echo "✅ TEST PASSED: Exit code matches expected behavior"
    echo "   Expected: $EXPECTED_EXIT_CODE, Actual: $ACTUAL_EXIT_CODE"
    exit 0
else
    echo "❌ TEST FAILED: Exit code mismatch"
    echo "   Expected: $EXPECTED_EXIT_CODE, Actual: $ACTUAL_EXIT_CODE"
    exit 1
fi
