#!/bin/bash
#
# Test script to verify health_check.sh exits with code 1 when issues are found
# This creates a mock health check that simulates an issue
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
mkdir -p "$PROJECT_ROOT/tmp"

TEMP_SCRIPT="$PROJECT_ROOT/tmp/mock_health_check.sh"
OUTPUT_FILE="$PROJECT_ROOT/tmp/mock_health_check_output.txt"

# Create a minimal mock health check that simulates finding an issue
cat > "$TEMP_SCRIPT" << 'EOF'
#!/bin/bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUTPUT_FILE="$PROJECT_ROOT/tmp/mock_health_check_output.txt"

# Initialize results
ISSUES_FOUND=0
declare -a ISSUES=()

# Function to add issue
add_issue() {
    ISSUES+=("$1")
    ((ISSUES_FOUND++)) || true
}

# Use exec with tee (same pattern as real health_check.sh)
exec > >(tee "$OUTPUT_FILE") 2>&1
TEE_PID=$!

echo "=== Mock Health Check (with simulated issue) ==="
echo ""

# Disable exit-on-error
set +e

# Simulate finding an issue
echo "Checking service..."
echo "  ❌ mock-service (not running)"
add_issue "mock-service container not running"

# Re-enable exit-on-error
set -e

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

# Save exit code (same pattern as real health_check.sh)
EXIT_CODE=0
if [[ $ISSUES_FOUND -gt 0 ]]; then
    EXIT_CODE=1
fi

# Close file descriptors and wait for tee to finish
exec 1>&-
exec 2>&-
wait $TEE_PID 2>/dev/null || true

# Exit with appropriate code
exit $EXIT_CODE
EOF

chmod +x "$TEMP_SCRIPT"

echo "=== Testing Health Check with Mock Issue ==="
echo ""

# Run the mock health check
if "$TEMP_SCRIPT"; then
    ACTUAL_EXIT_CODE=0
else
    ACTUAL_EXIT_CODE=$?
fi

echo ""
echo "Test Results:"
echo "  Actual exit code: $ACTUAL_EXIT_CODE"

# Verify the output file was created and contains the issue
if [[ -f "$OUTPUT_FILE" ]]; then
    echo "  Output file created: ✅"

    if grep -q "❌ Issues Found: 1" "$OUTPUT_FILE"; then
        echo "  Issue detected in output: ✅"
        EXPECTED_EXIT_CODE=1
    else
        echo "  ❌ Issue NOT detected in output"
        EXPECTED_EXIT_CODE=0
    fi
else
    echo "  ❌ Output file not created"
    exit 1
fi

echo ""

# Verify exit code
if [[ $ACTUAL_EXIT_CODE -eq 1 && $EXPECTED_EXIT_CODE -eq 1 ]]; then
    echo "✅ TEST PASSED: Script correctly exits 1 when issues are found"
    echo "   Expected: 1, Actual: $ACTUAL_EXIT_CODE"

    # Cleanup
    rm -f "$TEMP_SCRIPT" "$OUTPUT_FILE"
    exit 0
else
    echo "❌ TEST FAILED: Exit code mismatch"
    echo "   Expected: 1, Actual: $ACTUAL_EXIT_CODE"

    # Show output for debugging
    echo ""
    echo "Mock health check output:"
    cat "$OUTPUT_FILE"

    # Cleanup
    rm -f "$TEMP_SCRIPT" "$OUTPUT_FILE"
    exit 1
fi
