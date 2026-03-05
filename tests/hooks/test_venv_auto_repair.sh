#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Tests for _try_inline_venv_repair() in common.sh (OMN-3726)
#
# Usage: bash tests/hooks/test_venv_auto_repair.sh
#
# These tests exercise the auto-repair function in isolation by setting up
# a fake PLUGIN_ROOT in a temp directory and verifying behavior.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

PASS=0
FAIL=0

_assert_eq() {
    local label="$1" expected="$2" actual="$3"
    if [[ "$expected" == "$actual" ]]; then
        echo "  PASS: $label"
        ((PASS++))
    else
        echo "  FAIL: $label (expected='$expected', actual='$actual')"
        ((FAIL++))
    fi
}

_assert_file_exists() {
    local label="$1" path="$2"
    if [[ -f "$path" ]]; then
        echo "  PASS: $label"
        ((PASS++))
    else
        echo "  FAIL: $label (file not found: $path)"
        ((FAIL++))
    fi
}

_assert_file_not_exists() {
    local label="$1" path="$2"
    if [[ ! -f "$path" ]]; then
        echo "  PASS: $label"
        ((PASS++))
    else
        echo "  FAIL: $label (file should not exist: $path)"
        ((FAIL++))
    fi
}

# Clean up temp dirs on exit
TEMP_DIRS=()
cleanup() {
    for d in "${TEMP_DIRS[@]}"; do
        rm -rf "$d" 2>/dev/null || true
    done
    rm -f /tmp/omniclaude-venv-repair-failed 2>/dev/null || true
}
trap cleanup EXIT

# Create a minimal fake plugin root
_make_fake_plugin_root() {
    local tmp
    tmp=$(mktemp -d)
    TEMP_DIRS+=("$tmp")
    mkdir -p "$tmp/lib"
    echo "$tmp"
}

# ---------------------------------------------------------------------------
echo "=== Test 1: Successful venv creation when no venv exists ==="
FAKE_ROOT="$(_make_fake_plugin_root)"
rm -f /tmp/omniclaude-venv-repair-failed 2>/dev/null || true

# Run in a subshell that sources common.sh with our fake PLUGIN_ROOT
# We can't source common.sh directly because it exits on PYTHON_CMD failure
# So we extract and run _try_inline_venv_repair in isolation
result="$(
    export PLUGIN_ROOT="$FAKE_ROOT"
    # Define find_python and _try_inline_venv_repair by extracting from common.sh
    # Use awk to extract complete function bodies
    eval "$(awk '/^find_python\(\)/{found=1} found{print; if(/^}$/){found=0}}' "$REPO_ROOT/plugins/onex/hooks/scripts/common.sh")"
    eval "$(awk '/^_try_inline_venv_repair\(\)/{found=1} found{print; if(/^}$/){found=0}}' "$REPO_ROOT/plugins/onex/hooks/scripts/common.sh")"
    _try_inline_venv_repair 2>/dev/null || echo ""
)"

_assert_eq "returns python3 path" "${FAKE_ROOT}/lib/.venv/bin/python3" "$result"
_assert_file_exists "venv python3 is executable" "${FAKE_ROOT}/lib/.venv/bin/python3"
_assert_file_exists "sentinel written" "${FAKE_ROOT}/lib/.venv/.omniclaude-sentinel"
_assert_file_not_exists "no failure marker" "/tmp/omniclaude-venv-repair-failed"

# ---------------------------------------------------------------------------
echo ""
echo "=== Test 2: Rate-limiting prevents rapid re-repair ==="
FAKE_ROOT2="$(_make_fake_plugin_root)"

# Create a fresh failure marker
touch /tmp/omniclaude-venv-repair-failed

result2="$(
    export PLUGIN_ROOT="$FAKE_ROOT2"
    eval "$(awk '/^find_python\(\)/{found=1} found{print; if(/^}$/){found=0}}' "$REPO_ROOT/plugins/onex/hooks/scripts/common.sh")"
    eval "$(awk '/^_try_inline_venv_repair\(\)/{found=1} found{print; if(/^}$/){found=0}}' "$REPO_ROOT/plugins/onex/hooks/scripts/common.sh")"
    _try_inline_venv_repair 2>/dev/null || echo ""
)"

_assert_eq "returns empty when rate-limited" "" "$result2"
_assert_file_not_exists "venv not created when rate-limited" "${FAKE_ROOT2}/lib/.venv/bin/python3"

rm -f /tmp/omniclaude-venv-repair-failed 2>/dev/null || true

# ---------------------------------------------------------------------------
echo ""
echo "=== Test 3: Expired rate-limit marker allows retry ==="
FAKE_ROOT3="$(_make_fake_plugin_root)"

# Create an old failure marker (>5 min ago)
touch /tmp/omniclaude-venv-repair-failed
# Backdate it using python (cross-platform)
python3 -c "import os,time; os.utime('/tmp/omniclaude-venv-repair-failed', (time.time()-600, time.time()-600))" 2>/dev/null || true

result3="$(
    export PLUGIN_ROOT="$FAKE_ROOT3"
    eval "$(awk '/^find_python\(\)/{found=1} found{print; if(/^}$/){found=0}}' "$REPO_ROOT/plugins/onex/hooks/scripts/common.sh")"
    eval "$(awk '/^_try_inline_venv_repair\(\)/{found=1} found{print; if(/^}$/){found=0}}' "$REPO_ROOT/plugins/onex/hooks/scripts/common.sh")"
    _try_inline_venv_repair 2>/dev/null || echo ""
)"

_assert_eq "returns python3 path after cooldown" "${FAKE_ROOT3}/lib/.venv/bin/python3" "$result3"
_assert_file_exists "venv created after cooldown" "${FAKE_ROOT3}/lib/.venv/bin/python3"

rm -f /tmp/omniclaude-venv-repair-failed 2>/dev/null || true

# ---------------------------------------------------------------------------
echo ""
echo "=== Test 4: find_python detects repaired venv ==="
FAKE_ROOT4="$(_make_fake_plugin_root)"

# Run repair first, then find_python — with all override vars unset
repair_result="$(
    export PLUGIN_ROOT="$FAKE_ROOT4"
    unset PLUGIN_PYTHON_BIN 2>/dev/null || true
    unset OMNICLAUDE_PROJECT_ROOT 2>/dev/null || true
    eval "$(awk '/^find_python\(\)/{found=1} found{print; if(/^}$/){found=0}}' "$REPO_ROOT/plugins/onex/hooks/scripts/common.sh")"
    eval "$(awk '/^_try_inline_venv_repair\(\)/{found=1} found{print; if(/^}$/){found=0}}' "$REPO_ROOT/plugins/onex/hooks/scripts/common.sh")"
    _try_inline_venv_repair 2>/dev/null || true
    # Now find_python should find the repaired venv
    find_python
)"

# repair_result will have two lines: the repair path and the find_python path
fp_after="$(echo "$repair_result" | tail -1)"
_assert_eq "find_python finds repaired venv" "${FAKE_ROOT4}/lib/.venv/bin/python3" "$fp_after"

rm -f /tmp/omniclaude-venv-repair-failed 2>/dev/null || true

# ---------------------------------------------------------------------------
echo ""
echo "=== Test 5: Background pip install log is written ==="
# Check that repair log exists after test 1 ran
_assert_file_exists "repair log written" "/tmp/omniclaude-venv-repair.log"

# ---------------------------------------------------------------------------
echo ""
echo "=== Results ==="
echo "Passed: $PASS"
echo "Failed: $FAIL"
if (( FAIL > 0 )); then
    exit 1
fi
echo "All tests passed."
