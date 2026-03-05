#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# =============================================================================
# Tests for error-guard.sh (OMN-3724)
# =============================================================================
# Run: bash tests/hooks/test_error_guard.sh
# All tests must pass (exit 0). Any failure exits non-zero.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
GUARD_PATH="$REPO_ROOT/plugins/onex/hooks/scripts/error-guard.sh"

PASS=0
FAIL=0

assert_eq() {
    local test_name="$1"
    local expected="$2"
    local actual="$3"
    if [[ "$expected" == "$actual" ]]; then
        echo "  PASS: $test_name"
        ((PASS++)) || true
    else
        echo "  FAIL: $test_name (expected='$expected', actual='$actual')"
        ((FAIL++)) || true
    fi
}

# Clean up any previous test artifacts
TEST_LOG_DIR="${TMPDIR:-/tmp}/omniclaude-error-guard-test-$$"
rm -rf "$TEST_LOG_DIR" 2>/dev/null || true

echo "=== Test 1: Normal exit (code 0) passes through ==="
EXIT_CODE=0
bash -c "
    set -euo pipefail
    _OMNICLAUDE_HOOK_NAME='test-normal.sh'
    export _ERROR_GUARD_LOG_DIR='$TEST_LOG_DIR'
    source '$GUARD_PATH' 2>/dev/null || true
    echo 'output-normal'
    exit 0
" > /dev/null 2>&1 || EXIT_CODE=$?
assert_eq "exit code is 0" "0" "$EXIT_CODE"
# No error log should be written for normal exit
if [[ -f "$TEST_LOG_DIR/errors.log" ]]; then
    assert_eq "no error log for normal exit" "" "$(cat "$TEST_LOG_DIR/errors.log" 2>/dev/null)"
else
    assert_eq "no error log file for normal exit" "true" "true"
fi

echo ""
echo "=== Test 2: Exit 1 is swallowed, returns 0 ==="
rm -rf "$TEST_LOG_DIR" 2>/dev/null || true
EXIT_CODE=0
OUTPUT=$(bash -c "
    set -euo pipefail
    _OMNICLAUDE_HOOK_NAME='test-crash.sh'
    export _ERROR_GUARD_LOG_DIR='$TEST_LOG_DIR'
    source '$GUARD_PATH' 2>/dev/null || true
    echo 'before-crash'
    exit 1
" 2>/dev/null) || EXIT_CODE=$?
assert_eq "exit code is 0 after crash" "0" "$EXIT_CODE"
assert_eq "output before crash is captured" "before-crash" "$OUTPUT"

echo ""
echo "=== Test 3: Exit 42 is swallowed, returns 0 ==="
rm -rf "$TEST_LOG_DIR" 2>/dev/null || true
EXIT_CODE=0
bash -c "
    set -euo pipefail
    _OMNICLAUDE_HOOK_NAME='test-exit42.sh'
    export _ERROR_GUARD_LOG_DIR='$TEST_LOG_DIR'
    source '$GUARD_PATH' 2>/dev/null || true
    exit 42
" > /dev/null 2>&1 || EXIT_CODE=$?
assert_eq "exit code is 0 after exit 42" "0" "$EXIT_CODE"

echo ""
echo "=== Test 4: Error is logged to file ==="
rm -rf "$TEST_LOG_DIR" 2>/dev/null || true
bash -c "
    set -euo pipefail
    _OMNICLAUDE_HOOK_NAME='test-logged.sh'
    export _ERROR_GUARD_LOG_DIR='$TEST_LOG_DIR'
    source '$GUARD_PATH' 2>/dev/null || true
    exit 7
" > /dev/null 2>&1 || true
if [[ -f "$TEST_LOG_DIR/errors.log" ]]; then
    LOG_CONTENT=$(cat "$TEST_LOG_DIR/errors.log")
    if echo "$LOG_CONTENT" | grep -q "test-logged.sh exited with code 7"; then
        assert_eq "error logged with hook name and exit code" "true" "true"
    else
        assert_eq "error logged with hook name and exit code" "contains 'test-logged.sh exited with code 7'" "$LOG_CONTENT"
    fi
else
    assert_eq "error log file exists" "true" "false"
fi

echo ""
echo "=== Test 5: set -e triggered failure is caught ==="
rm -rf "$TEST_LOG_DIR" 2>/dev/null || true
EXIT_CODE=0
bash -c "
    set -euo pipefail
    _OMNICLAUDE_HOOK_NAME='test-sete.sh'
    export _ERROR_GUARD_LOG_DIR='$TEST_LOG_DIR'
    source '$GUARD_PATH' 2>/dev/null || true
    false  # This triggers set -e
    echo 'should-not-reach'
" > /dev/null 2>&1 || EXIT_CODE=$?
assert_eq "set -e failure returns 0" "0" "$EXIT_CODE"

echo ""
echo "=== Test 6: Stdin is drained on failure ==="
rm -rf "$TEST_LOG_DIR" 2>/dev/null || true
EXIT_CODE=0
echo '{"test": "data"}' | bash -c "
    set -euo pipefail
    _OMNICLAUDE_HOOK_NAME='test-drain.sh'
    export _ERROR_GUARD_LOG_DIR='$TEST_LOG_DIR'
    source '$GUARD_PATH' 2>/dev/null || true
    # Don't read stdin, just crash
    exit 1
" > /dev/null 2>&1 || EXIT_CODE=$?
assert_eq "stdin drained on failure" "0" "$EXIT_CODE"

echo ""
echo "=== Test 7: Missing error-guard.sh is graceful (|| true) ==="
EXIT_CODE=0
bash -c "
    set -euo pipefail
    _OMNICLAUDE_HOOK_NAME='test-missing.sh'
    source '/nonexistent/error-guard.sh' 2>/dev/null || true
    echo 'still-running'
    exit 0
" > /dev/null 2>&1 || EXIT_CODE=$?
assert_eq "missing guard is graceful" "0" "$EXIT_CODE"

echo ""
echo "=== Test 8: All 12 hook scripts source error-guard.sh ==="
HOOK_DIR="$REPO_ROOT/plugins/onex/hooks/scripts"
EXPECTED_HOOKS=(
    "session-start.sh"
    "user-prompt-submit.sh"
    "pre_tool_use_authorization_shim.sh"
    "pre_tool_use_bash_guard.sh"
    "pre-tool-use-quality.sh"
    "session-end.sh"
    "stop.sh"
    "pre-compact.sh"
    "post-tool-use-quality.sh"
    "post-tool-delegation-counter.sh"
    "post-skill-delegation-enforcer.sh"
    "user-prompt-delegation-rule.sh"
)
for hook in "${EXPECTED_HOOKS[@]}"; do
    if grep -q 'error-guard.sh' "$HOOK_DIR/$hook" 2>/dev/null; then
        assert_eq "$hook sources error-guard.sh" "true" "true"
    else
        assert_eq "$hook sources error-guard.sh" "true" "false"
    fi
done

# Clean up
rm -rf "$TEST_LOG_DIR" 2>/dev/null || true

echo ""
echo "========================================="
echo "Results: $PASS passed, $FAIL failed"
echo "========================================="

if [[ $FAIL -gt 0 ]]; then
    exit 1
fi
exit 0
