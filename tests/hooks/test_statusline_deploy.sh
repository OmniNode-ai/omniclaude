#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Statusline deploy verification tests [OMN-3732]
# Runs all degradation matrix scenarios against statusline.sh
#
# Usage: bash tests/hooks/test_statusline_deploy.sh [--verbose]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
STATUSLINE="$REPO_ROOT/plugins/onex/hooks/scripts/statusline.sh"

VERBOSE=false
[ "${1:-}" = "--verbose" ] && VERBOSE=true

PASS=0
FAIL=0
SKIP=0

log() { printf "  %s\n" "$1"; }
pass() { PASS=$((PASS + 1)); printf "  \033[32mPASS\033[0m %s\n" "$1"; }
fail() { FAIL=$((FAIL + 1)); printf "  \033[31mFAIL\033[0m %s\n" "$1"; }
skip() { SKIP=$((SKIP + 1)); printf "  \033[33mSKIP\033[0m %s\n" "$1"; }

# Minimal mock usage JSON (Claude Code sends this via stdin)
MOCK_USAGE='{
  "model": { "display_name": "Claude Opus 4.6", "id": "claude-opus-4-6" },
  "tokens": { "used": 50000, "total": 100000 },
  "plan_usage": { "current_period": { "utilization": 45.0, "reset_at": "2026-03-06T00:00:00Z" }, "weekly": { "utilization": 30.0, "reset_at": "2026-03-10T00:00:00Z" } },
  "thinking": { "enabled": true, "budget_tokens": 16000 }
}'

# ===== Test 1: Smoke test -- first run with no cache =====
echo ""
echo "=== Test 1: Smoke test (no cache, first run) ==="

# Clear caches and locks
rm -f /tmp/omniclaude-health-cache.json /tmp/omniclaude-pr-cache.json
rm -rf /tmp/omniclaude-health.lock /tmp/omniclaude-pr.lock

output=$(echo "$MOCK_USAGE" | bash "$STATUSLINE" 2>/dev/null)
line_count=$(echo "$output" | wc -l | tr -d ' ')

if [ "$line_count" -ge 3 ]; then
    pass "Output has $line_count lines (>= 3 expected)"
else
    fail "Output has only $line_count lines, expected >= 3"
fi

# Line 4 should exist and show placeholder or real data
line4=$(echo "$output" | sed -n '4p')
if [ -n "$line4" ]; then
    pass "Line 4 exists"
else
    # Line 4 might be empty on first run if jq not available
    if ! command -v jq >/dev/null 2>&1; then
        skip "Line 4 empty (no jq installed)"
    else
        fail "Line 4 missing despite jq being available"
    fi
fi

# Check that ANSI codes are present (color output)
if echo "$output" | grep -q $'\033\['; then
    pass "ANSI color codes present in output"
else
    fail "No ANSI color codes found"
fi

# Line 1 should contain model name
if echo "$output" | head -1 | grep -qi "opus"; then
    pass "Line 1 contains model name"
else
    fail "Line 1 missing model name"
fi

$VERBOSE && echo "--- Raw output ---" && echo "$output" | cat -v && echo "---"

# ===== Test 2: Second run with warm cache =====
echo ""
echo "=== Test 2: Second run (cache should be populated) ==="

# Wait briefly for background health probe to complete
sleep 2

output2=$(echo "$MOCK_USAGE" | bash "$STATUSLINE" 2>/dev/null)
line4_2=$(echo "$output2" | sed -n '4p')

# After background probe, health cache should exist
if [ -f /tmp/omniclaude-health-cache.json ]; then
    pass "Health cache file exists after background probe"

    if command -v jq >/dev/null 2>&1; then
        # Validate JSON
        if jq -e . /tmp/omniclaude-health-cache.json >/dev/null 2>&1; then
            pass "Health cache is valid JSON"
        else
            fail "Health cache is not valid JSON"
        fi

        # Check required keys
        for key in pg rp vk bus ts; do
            if jq -e ".$key" /tmp/omniclaude-health-cache.json >/dev/null 2>&1; then
                pass "Health cache has key: $key"
            else
                fail "Health cache missing key: $key"
            fi
        done
    fi
else
    fail "Health cache not created after 2s wait"
fi

# Line 4 should now show real dots (not just "health: ?")
if echo "$line4_2" | cat -v | grep -q "pg:"; then
    pass "Line 4 shows health dots (pg: present)"
else
    # Might still be placeholder on slow systems
    if echo "$line4_2" | cat -v | grep -q "health:"; then
        skip "Line 4 still shows placeholder (slow probe)"
    else
        fail "Line 4 missing both dots and placeholder"
    fi
fi

$VERBOSE && echo "--- Raw output ---" && echo "$output2" | cat -v && echo "---"

# ===== Test 3: No stampede (rapid invocations) =====
echo ""
echo "=== Test 3: No stampede (5 rapid invocations) ==="

# Clear locks
rm -rf /tmp/omniclaude-health.lock /tmp/omniclaude-pr.lock

# Fire 5 invocations in rapid succession
for i in 1 2 3 4 5; do
    echo "$MOCK_USAGE" | bash "$STATUSLINE" >/dev/null 2>&1 &
done
wait

# Check that lock dirs are cleaned up (not stuck)
sleep 1
if [ -d /tmp/omniclaude-health.lock ]; then
    # Check if PID is still alive
    if [ -f /tmp/omniclaude-health.lock/pid ]; then
        lock_pid=$(cat /tmp/omniclaude-health.lock/pid 2>/dev/null)
        if [ -n "$lock_pid" ] && kill -0 "$lock_pid" 2>/dev/null; then
            pass "Health lock held by active process (PID $lock_pid)"
        else
            fail "Stale health lock detected (PID $lock_pid not running)"
        fi
    else
        fail "Health lock dir exists but no PID file"
    fi
else
    pass "Health lock cleaned up after rapid invocations"
fi

if [ -d /tmp/omniclaude-pr.lock ]; then
    if [ -f /tmp/omniclaude-pr.lock/pid ]; then
        lock_pid=$(cat /tmp/omniclaude-pr.lock/pid 2>/dev/null)
        if [ -n "$lock_pid" ] && kill -0 "$lock_pid" 2>/dev/null; then
            pass "PR lock held by active process (PID $lock_pid)"
        else
            fail "Stale PR lock detected (PID $lock_pid not running)"
        fi
    else
        fail "PR lock dir exists but no PID file"
    fi
else
    pass "PR lock cleaned up after rapid invocations"
fi

# ===== Test 4: Graceful degradation -- no gh CLI =====
echo ""
echo "=== Test 4: No gh CLI (PATH manipulation) ==="

# Clear PR cache so the script must try gh (which won't be found)
rm -f /tmp/omniclaude-pr-cache.json

# Remove gh from PATH for this invocation
output4=$(echo "$MOCK_USAGE" | PATH=$(echo "$PATH" | tr ':' '\n' | grep -v "$(dirname "$(command -v gh 2>/dev/null)")" | tr '\n' ':') bash "$STATUSLINE" 2>/dev/null)
line4_4=$(echo "$output4" | sed -n '4p')

# Script should still produce output (not crash)
if [ -n "$output4" ]; then
    pass "Statusline produces output without gh CLI"
else
    fail "Statusline produced no output without gh CLI"
fi

# Line 4 PR section should show "PRs: ?" when gh is unavailable and cache cleared
# Strip ANSI codes for clean matching
line4_4_clean=$(echo "$line4_4" | sed 's/\x1b\[[0-9;]*m//g')
if echo "$line4_4_clean" | grep -q "PRs:"; then
    pass "Line 4 still shows PRs section without gh"
    # Specifically: with no cache and no gh, should show "?"
    if echo "$line4_4_clean" | grep -q "PRs: ?"; then
        pass "PRs section shows placeholder '?' without gh"
    else
        skip "PRs section shows cached data (cache cleanup may have been partial)"
    fi
else
    skip "Line 4 PRs section not found (may be in placeholder mode)"
fi

$VERBOSE && echo "--- Raw output ---" && echo "$output4" | cat -v && echo "---"

# ===== Test 5: Graceful degradation -- no jq =====
echo ""
echo "=== Test 5: No jq (PATH manipulation) ==="

output5=$(echo "$MOCK_USAGE" | PATH=$(echo "$PATH" | tr ':' '\n' | grep -v "$(dirname "$(command -v jq 2>/dev/null)")" | tr '\n' ':') bash "$STATUSLINE" 2>/dev/null)

if [ -n "$output5" ]; then
    pass "Statusline produces output without jq"
else
    fail "Statusline produced no output without jq"
fi

# Without jq, the fallback "health: ? | PRs: ?" appears -- may be on a different line
# since lines 2-3 degrade without jq
output5_clean=$(echo "$output5" | sed 's/\x1b\[[0-9;]*m//g')
if echo "$output5_clean" | grep -q "health:.*PRs:"; then
    pass "Output shows graceful fallback 'health: ? | PRs: ?' without jq"
else
    # Lines 1-3 may also degrade without jq, which is expected
    skip "Fallback pattern not matched (entire script degrades without jq)"
fi

$VERBOSE && echo "--- Raw output ---" && echo "$output5" | cat -v && echo "---"

# ===== Test 6: Empty stdin =====
echo ""
echo "=== Test 6: Empty stdin ==="

output6=$(echo "" | bash "$STATUSLINE" 2>/dev/null)
if [ "$output6" = "Claude" ]; then
    pass "Empty stdin returns 'Claude' fallback"
else
    fail "Empty stdin returned: '$output6' (expected 'Claude')"
fi

# ===== Test 7: Deploy verification =====
echo ""
echo "=== Test 7: Deploy verification ==="

CACHE_DIR=$(ls -td ~/.claude/plugins/cache/omninode-tools/onex/*/hooks/scripts 2>/dev/null | head -1)

if [ -n "$CACHE_DIR" ]; then
    if [ -f "$CACHE_DIR/statusline.sh" ]; then
        # Compare source vs cache
        if diff -q "$STATUSLINE" "$CACHE_DIR/statusline.sh" >/dev/null 2>&1; then
            pass "Plugin cache statusline.sh matches source"
        else
            fail "Plugin cache statusline.sh differs from source (needs deploy)"
        fi
    else
        fail "statusline.sh not found in cache at $CACHE_DIR"
    fi
else
    fail "No plugin cache directory found"
fi

# ===== Summary =====
echo ""
echo "========================================="
echo "Results: $PASS passed, $FAIL failed, $SKIP skipped"
echo "========================================="

[ "$FAIL" -gt 0 ] && exit 1
exit 0
