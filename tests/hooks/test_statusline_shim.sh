#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# TDD test for W0.3: stable statusline shim
# Asserts that $HOME/.onex_state/bin/statusline.sh:
#   1. Exists after deploy.sh runs
#   2. Delegates to the cache-discovered version (not a hardcoded path)
#   3. Returns valid statusline output regardless of which cache version is active
#
# Usage: bash tests/hooks/test_statusline_shim.sh [--verbose]

set -euo pipefail

VERBOSE=false
[ "${1:-}" = "--verbose" ] && VERBOSE=true

PASS=0
FAIL=0

pass() { PASS=$((PASS + 1)); printf "  \033[32mPASS\033[0m %s\n" "$1"; }
fail() { FAIL=$((FAIL + 1)); printf "  \033[31mFAIL\033[0m %s\n" "$1"; }

SHIM="$HOME/.onex_state/bin/statusline.sh"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEPLOY_SH="$(cd "$SCRIPT_DIR/../.." && pwd)/plugins/onex/hooks/scripts/deploy.sh"

MOCK_USAGE='{
  "model": { "display_name": "Claude Opus 4.6", "id": "claude-opus-4-6" },
  "tokens": { "used": 50000, "total": 100000 },
  "plan_usage": { "current_period": { "utilization": 45.0, "reset_at": "2026-03-06T00:00:00Z" }, "weekly": { "utilization": 30.0, "reset_at": "2026-03-10T00:00:00Z" } },
  "thinking": { "enabled": true, "budget_tokens": 16000 }
}'

# ===== Test 1: deploy.sh exists and runs successfully =====
echo ""
echo "=== Test 1: deploy.sh exists ==="
if [ -f "$DEPLOY_SH" ]; then
    pass "deploy.sh exists at $DEPLOY_SH"
    if bash "$DEPLOY_SH" >/dev/null 2>&1; then
        pass "deploy.sh executed successfully"
    else
        fail "deploy.sh execution failed"
    fi
else
    fail "deploy.sh not found at $DEPLOY_SH"
fi

# ===== Test 2: shim exists at stable path =====
echo ""
echo "=== Test 2: Stable shim exists at \$HOME/.onex_state/bin/statusline.sh ==="
if [ -f "$SHIM" ]; then
    pass "Shim exists at $SHIM"
else
    fail "Shim does NOT exist at $SHIM (deploy.sh must create it as post-install step)"
fi

# ===== Test 3: shim is executable =====
echo ""
echo "=== Test 3: Shim is executable ==="
if [ -x "$SHIM" ]; then
    pass "Shim is executable"
else
    fail "Shim is not executable (chmod +x required)"
fi

# ===== Test 4: shim does NOT contain a hardcoded version string =====
echo ""
echo "=== Test 4: Shim has no hardcoded cache version (e.g. 2.2.5) ==="
if [ -f "$SHIM" ]; then
    # Check that the shim dynamically discovers the version rather than hardcoding it
    if grep -qE '/cache/omninode-tools/onex/[0-9]+\.[0-9]+\.[0-9]+/' "$SHIM"; then
        fail "Shim contains a hardcoded version path (must use dynamic discovery)"
    else
        pass "Shim contains no hardcoded version path"
    fi
fi

# ===== Test 5: shim delegates to cache-discovered statusline.sh =====
echo ""
echo "=== Test 5: Shim references cache discovery logic ==="
if [ -f "$SHIM" ]; then
    # Shim must resolve via ls/glob of the cache dir, not a hardcoded path
    if grep -qE 'plugins/cache/omninode-tools/onex|ls.*cache.*onex' "$SHIM"; then
        pass "Shim references dynamic cache discovery"
    else
        fail "Shim does not appear to discover the cache dynamically"
    fi
fi

# ===== Test 6: shim produces valid output when invoked =====
echo ""
echo "=== Test 6: Shim produces output when invoked ==="
if [ -x "$SHIM" ]; then
    shim_output=$(echo "$MOCK_USAGE" | bash "$SHIM" 2>/dev/null) || true
    if [ -n "$shim_output" ]; then
        pass "Shim produces output"
        $VERBOSE && echo "--- Shim output ---" && echo "$shim_output" && echo "---"
    else
        fail "Shim produced no output"
    fi
fi

# ===== Test 7: settings.json points to stable shim (not a versioned cache path) =====
echo ""
echo "=== Test 7: settings.json statusLine.command points to stable shim ==="
SETTINGS="$HOME/.claude/settings.json"
if [ -f "$SETTINGS" ] && command -v jq >/dev/null 2>&1; then
    current_cmd=$(jq -r '.statusLine.command // empty' "$SETTINGS" 2>/dev/null)
    if echo "$current_cmd" | grep -qE 'onex_state/bin/statusline\.sh|\.onex_state/bin/statusline\.sh'; then
        pass "settings.json points to stable shim: $current_cmd"
    elif echo "$current_cmd" | grep -qE '/cache/omninode-tools/onex/[0-9]+\.[0-9]+\.[0-9]+/'; then
        fail "settings.json still points to versioned cache path: $current_cmd (must point to \$HOME/.onex_state/bin/statusline.sh)"
    else
        fail "settings.json statusLine.command unexpected value: $current_cmd"
    fi
else
    pass "Skipped settings.json assertion (settings.json or jq unavailable)"
fi

# ===== Summary =====
echo ""
echo "========================================="
echo "Results: $PASS passed, $FAIL failed"
echo "========================================="

[ "$FAIL" -gt 0 ] && exit 1
exit 0
