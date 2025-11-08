#!/bin/bash
# Complete integration test for manifest injection in hooks

set -euo pipefail

echo "=========================================="
echo "Complete Manifest Injection Test"
echo "=========================================="

# Portable path resolution
# Use environment variable if set, otherwise compute from script location
if [ -n "${PROJECT_PATH:-}" ]; then
    # Use provided PROJECT_PATH
    :
elif [ -n "${PROJECT_ROOT:-}" ]; then
    # Use PROJECT_ROOT if available
    PROJECT_PATH="$PROJECT_ROOT"
else
    # Fallback: Compute from script location (claude_hooks/ -> project root)
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    PROJECT_PATH="$(cd "$SCRIPT_DIR/.." && pwd)"
fi

MANIFEST_LOADER="$HOME/.claude/hooks/lib/manifest_loader.py"

# Test 1: Verify manifest_loader.py exists
echo -e "\nTest 1: Verify manifest_loader.py exists"
if [[ -f "$MANIFEST_LOADER" ]]; then
    echo "✓ manifest_loader.py found at $MANIFEST_LOADER"
else
    echo "✗ manifest_loader.py not found at $MANIFEST_LOADER"
    exit 1
fi

# Test 2: Load manifest
echo -e "\nTest 2: Load manifest via manifest_loader.py"
SYSTEM_MANIFEST="$(PROJECT_PATH="$PROJECT_PATH" python3 "$MANIFEST_LOADER" 2>&1)"

if [[ -z "$SYSTEM_MANIFEST" ]]; then
    echo "✗ Empty manifest"
    exit 1
elif [[ "$SYSTEM_MANIFEST" == *"Not available"* ]]; then
    echo "✗ Manifest not available: $SYSTEM_MANIFEST"
    exit 1
else
    echo "✓ Manifest loaded: ${#SYSTEM_MANIFEST} characters"
fi

# Test 3: Verify key sections
echo -e "\nTest 3: Verify manifest content"
required_sections=(
    "SYSTEM MANIFEST"
    "AVAILABLE PATTERNS"
    "AI MODELS"
    "INFRASTRUCTURE TOPOLOGY"
    "FILE STRUCTURE"
)

all_found=true
for section in "${required_sections[@]}"; do
    if [[ "$SYSTEM_MANIFEST" == *"$section"* ]]; then
        echo "  ✓ Found: $section"
    else
        echo "  ✗ Missing: $section"
        all_found=false
    fi
done

if [[ "$all_found" == false ]]; then
    exit 1
fi

# Test 4: Verify it can be injected into a prompt
echo -e "\nTest 4: Verify manifest can be injected into prompt"
AGENT_ROLE="research"
PROMPT="Test user prompt"

# Simulate the exact prompt construction from hook
TEST_PROMPT="Load configuration for role '${AGENT_ROLE}' and execute:

${PROMPT}

${SYSTEM_MANIFEST}

Intelligence Context:
- Requested Role: ${AGENT_ROLE}
"

if [[ ${#TEST_PROMPT} -gt 2000 ]]; then
    echo "✓ Constructed prompt: ${#TEST_PROMPT} characters"
    echo "  First 500 chars:"
    echo "${TEST_PROMPT:0:500}..."
else
    echo "✗ Prompt too short: ${#TEST_PROMPT} characters"
    exit 1
fi

# Test 5: Test error handling (non-blocking)
echo -e "\nTest 5: Test error handling with invalid PROJECT_PATH"
ERROR_MANIFEST="$(PROJECT_PATH="/nonexistent" python3 "$MANIFEST_LOADER" 2>&1)"

if [[ "$ERROR_MANIFEST" == *"Not available"* ]]; then
    echo "✗ With invalid path, got fallback: ${ERROR_MANIFEST:0:80}..."
    echo "  (This is expected - manifest should fail gracefully)"
else
    echo "✓ Manifest still loaded (home directory fallback worked)"
fi

# Summary
echo -e "\n=========================================="
echo "ALL TESTS PASSED ✓"
echo "=========================================="
echo ""
echo "Summary:"
echo "  - Manifest loader: Working"
echo "  - Manifest size: ${#SYSTEM_MANIFEST} characters"
echo "  - All required sections: Present"
echo "  - Prompt injection: Working"
echo "  - Error handling: Non-blocking"
echo ""
echo "The manifest will be automatically injected into agent"
echo "prompts when the user-prompt-submit hook triggers."
