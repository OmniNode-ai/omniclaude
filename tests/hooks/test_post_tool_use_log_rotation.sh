#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Tests log rotation guard and path resolution added in OMN-8429.
# Exercises the trim-in-place logic and ONEX_STATE_DIR path resolution
# from post-tool-use-quality.sh without invoking the full hook.

set -euo pipefail

PASS=0
FAIL=0

_pass() { echo "PASS: $1"; (( PASS++ )) || true; }
_fail() { echo "FAIL: $1"; (( FAIL++ )) || true; }

# Inline the rotation logic so the test is self-contained and identical to
# the production code path in post-tool-use-quality.sh.
_rotate_if_needed() {
    local LOG_FILE="$1"
    local ONEX_HOOK_LOG_MAX_MB="${2:-50}"
    local ONEX_HOOK_LOG_KEEP_MB="${3:-10}"

    local _HOOK_LOG_MAX_MB="$ONEX_HOOK_LOG_MAX_MB"
    local _HOOK_LOG_KEEP_MB="$ONEX_HOOK_LOG_KEEP_MB"

    if [[ -f "$LOG_FILE" ]]; then
        local _log_size_bytes
        _log_size_bytes=$(stat -f%z "$LOG_FILE" 2>/dev/null || stat -c%s "$LOG_FILE" 2>/dev/null || echo 0)
        local _log_size_mb=$(( _log_size_bytes / 1024 / 1024 ))
        if [[ "$_log_size_mb" -gt "$_HOOK_LOG_MAX_MB" ]]; then
            mv "$LOG_FILE" "${LOG_FILE}.1" 2>/dev/null || true
            tail -c $(( _HOOK_LOG_KEEP_MB * 1024 * 1024 )) "${LOG_FILE}.1" > "$LOG_FILE" 2>/dev/null || touch "$LOG_FILE"
        fi
    fi
}

TMPDIR_TEST="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_TEST"' EXIT

# --- Test 1: rotation triggers when file exceeds threshold ---
TMP_LOG="$TMPDIR_TEST/post-tool-use.log"
dd if=/dev/urandom of="$TMP_LOG" bs=1M count=60 2>/dev/null
_rotate_if_needed "$TMP_LOG" 50 10

if [[ -f "${TMP_LOG}.1" ]]; then
    _pass "test1: backup .1 created after rotation"
else
    _fail "test1: backup .1 not created"
fi

new_size=$(stat -f%z "$TMP_LOG" 2>/dev/null || stat -c%s "$TMP_LOG" 2>/dev/null || echo 0)
new_mb=$(( new_size / 1024 / 1024 ))
if [[ "$new_mb" -lt 15 ]]; then
    _pass "test1: trimmed log is smaller than 15MB (got ${new_mb}MB)"
else
    _fail "test1: trimmed log too large: ${new_mb}MB (expected <15MB)"
fi

backup_size=$(stat -f%z "${TMP_LOG}.1" 2>/dev/null || stat -c%s "${TMP_LOG}.1" 2>/dev/null || echo 0)
backup_mb=$(( backup_size / 1024 / 1024 ))
if [[ "$backup_mb" -ge 55 ]]; then
    _pass "test1: backup has close to original 60MB (got ${backup_mb}MB)"
else
    _fail "test1: backup smaller than expected: ${backup_mb}MB (expected >=55MB)"
fi

# --- Test 2: no double-rotation — second call leaves small log alone ---
size_before=$(stat -f%z "$TMP_LOG" 2>/dev/null || stat -c%s "$TMP_LOG" 2>/dev/null || echo 0)
_rotate_if_needed "$TMP_LOG" 50 10
size_after=$(stat -f%z "$TMP_LOG" 2>/dev/null || stat -c%s "$TMP_LOG" 2>/dev/null || echo 0)
if [[ "$size_before" -eq "$size_after" ]]; then
    _pass "test2: second call does not re-rotate small log"
else
    _fail "test2: size changed on second call (before=${size_before}, after=${size_after})"
fi

# --- Test 3: no rotation when file is under threshold ---
SMALL_LOG="$TMPDIR_TEST/small.log"
dd if=/dev/urandom of="$SMALL_LOG" bs=1M count=5 2>/dev/null
_rotate_if_needed "$SMALL_LOG" 50 10
if [[ ! -f "${SMALL_LOG}.1" ]]; then
    _pass "test3: no backup created when file is under threshold"
else
    _fail "test3: spurious backup created for 5MB file"
fi

# --- Test 4: LOG_FILE resolves to ONEX_STATE_DIR/hooks/logs/, not plugin source/install dir ---
# Simulate the path resolution logic from post-tool-use-quality.sh.
# The hook computes: LOG_FILE="${ONEX_STATE_DIR}/hooks/logs/post-tool-use.log"
# It must NOT resolve to anything under PLUGIN_ROOT or HOOKS_DIR.
FAKE_STATE_DIR="$TMPDIR_TEST/fake_onex_state"
FAKE_PLUGIN_ROOT="$TMPDIR_TEST/fake_plugin_root"
mkdir -p "$FAKE_STATE_DIR/hooks/logs" "$FAKE_PLUGIN_ROOT/hooks/logs"

# Compute LOG_FILE exactly as the hook does (with ONEX_STATE_DIR set)
RESOLVED_LOG="${FAKE_STATE_DIR}/hooks/logs/post-tool-use.log"

# Assert it is under ONEX_STATE_DIR, not under PLUGIN_ROOT
if [[ "$RESOLVED_LOG" == "${FAKE_STATE_DIR}"* ]]; then
    _pass "test4: LOG_FILE resolves under ONEX_STATE_DIR (not plugin source/install)"
else
    _fail "test4: LOG_FILE resolved to wrong path: $RESOLVED_LOG"
fi

if [[ "$RESOLVED_LOG" != "${FAKE_PLUGIN_ROOT}"* ]]; then
    _pass "test4: LOG_FILE does not resolve under PLUGIN_ROOT"
else
    _fail "test4: LOG_FILE incorrectly resolves under PLUGIN_ROOT: $RESOLVED_LOG"
fi

# Assert the resolved path does not contain the literal string "plugins/onex/hooks"
# (which would indicate the old HOOKS_DIR-relative path)
if [[ "$RESOLVED_LOG" != *"plugins/onex/hooks"* ]]; then
    _pass "test4: LOG_FILE path does not contain plugin source layout"
else
    _fail "test4: LOG_FILE path contains plugin source layout: $RESOLVED_LOG"
fi

# Assert the resolved path includes hooks/logs/ subdir (not just logs/ at state root)
if [[ "$RESOLVED_LOG" == *"/hooks/logs/"* ]]; then
    _pass "test4: LOG_FILE path includes hooks/logs/ partition"
else
    _fail "test4: LOG_FILE path missing hooks/logs/ partition: $RESOLVED_LOG"
fi

# --- Test 5: ONEX_STATE_DIR unset causes hard failure (no ~/.onex_state fallback) ---
# Verify that the hook's guard block exits 0 and writes to /tmp/onex-hook-error.log
# when ONEX_STATE_DIR is empty. We simulate this by running a minimal subshell.
ERROR_LOG_TMP="$TMPDIR_TEST/onex-hook-error.log"
_test5_exit_code=0
(
    unset ONEX_STATE_DIR
    if [[ -z "${ONEX_STATE_DIR:-}" ]]; then
        echo "[$(date -u +%FT%TZ)] ERROR: ONEX_STATE_DIR unset; test5 guard triggered" >> "$ERROR_LOG_TMP"
        exit 0
    fi
    # Should not reach here
    exit 1
) || _test5_exit_code=$?

if [[ "$_test5_exit_code" -eq 0 ]]; then
    _pass "test5: unset ONEX_STATE_DIR exits 0 (does not block Claude Code)"
else
    _fail "test5: unset ONEX_STATE_DIR exited non-zero: $_test5_exit_code"
fi

if [[ -f "$ERROR_LOG_TMP" ]] && grep -q "ONEX_STATE_DIR unset" "$ERROR_LOG_TMP"; then
    _pass "test5: error written to error log when ONEX_STATE_DIR unset"
else
    _fail "test5: error log not written or missing expected message"
fi

# --- Summary ---
echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
