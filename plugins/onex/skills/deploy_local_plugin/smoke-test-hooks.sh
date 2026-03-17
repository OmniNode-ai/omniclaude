#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# smoke-test-hooks.sh — fast hook output validation
#
# Runs every hook that produces JSON output and verifies:
#   - exits 0
#   - stdout is valid JSON (or empty, for pass-through hooks)
#   - stdout does not contain stdout-pollution patterns ("tier=...", non-JSON prefixes)
#
# Designed to run in ~15 seconds. Use before deploying to catch broken hooks.
#
# Usage:
#   # Against the deployed cache (default):
#   bash smoke-test-hooks.sh
#
#   # Against a specific plugin root:
#   bash smoke-test-hooks.sh /path/to/plugin/root
#
# Exit code: 0 = all pass, 1 = one or more failures
#
# Wire into deploy.sh post-rsync step:
#   bash "$(dirname "$0")/smoke-test-hooks.sh" "$TARGET" \
#     || { echo "Smoke tests failed — aborting deploy"; exit 1; }

set -uo pipefail

PLUGIN_ROOT="${1:-$HOME/.claude/plugins/cache/omninode-tools/onex/2.2.5}"
HOOKS_SCRIPTS="${PLUGIN_ROOT}/hooks/scripts"

if [[ ! -d "$HOOKS_SCRIPTS" ]]; then
    echo "ERROR: hooks/scripts not found at ${HOOKS_SCRIPTS}"
    exit 1
fi

PASS=0
FAIL=0

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RESET='\033[0m'

# test_hook <name> <script_path> <json_input> <timeout_sec>
#
# Verifies:
#   1. exit code 0 (or timeout exit 124 is reported separately)
#   2. stdout is non-empty valid JSON (empty stdout is also accepted for pass-through hooks)
#   3. stdout does not start with a non-JSON prefix (catches stdout pollution bugs)
test_hook() {
    local name="$1"
    local script="$2"
    local input="$3"
    local timeout_sec="${4:-8}"

    local out_file; out_file="$(mktemp /tmp/smoke-hook-out.XXXXXX)"
    local err_file; err_file="$(mktemp /tmp/smoke-hook-err.XXXXXX)"
    local errors=""

    # Use the `timeout` command for reliable wall-clock enforcement.
    # timeout exits 124 on timeout, 0-125 on normal exit.
    echo "$input" | timeout "$timeout_sec" bash "$script" > "$out_file" 2> "$err_file"
    local exit_code=$?

    if [[ "$exit_code" -eq 124 ]]; then
        errors+=" timeout(>${timeout_sec}s)"
    elif [[ "$exit_code" -ne 0 ]]; then
        errors+=" exit=${exit_code}"
    fi

    if [[ -z "$errors" ]]; then
        local stdout_content
        stdout_content="$(cat "$out_file")"

        if [[ -n "$stdout_content" ]]; then
            # Stdout must be valid JSON when non-empty
            if ! echo "$stdout_content" | python3 -m json.tool > /dev/null 2>&1; then
                errors+=" invalid-json"
                echo "       stdout: $(echo "$stdout_content" | head -c 200)" >&2
            fi

            # Check for stdout pollution: "tier=..." or any word= prefix before JSON.
            # This is the regression guard for OMN-4566:
            # capability_probe.py printed "tier=event_bus" to stdout, prepending it to the
            # JSON body, which caused Claude Code's JSON parser to fail on every session start.
            if echo "$stdout_content" | grep -qE '^[a-zA-Z_][a-zA-Z0-9_]*='; then
                local first_line
                first_line="$(echo "$stdout_content" | head -1)"
                errors+=" stdout-pollution(first-line: ${first_line})"
            fi
        fi
    fi

    rm -f "$out_file" "$err_file"

    if [[ -n "$errors" ]]; then
        echo -e "  ${RED}FAIL${RESET} [${name}]:${errors}"
        FAIL=$(( FAIL + 1 ))
    else
        echo -e "  ${GREEN}PASS${RESET} [${name}]"
        PASS=$(( PASS + 1 ))
    fi
}

echo -e "${YELLOW}Smoke-testing hooks in: ${PLUGIN_ROOT}${RESET}"
echo

UPS_INPUT='{"session_id":"smoke-test","hook_event_name":"UserPromptSubmit","prompt":"smoke test","cwd":"/tmp"}'
SESSION_INPUT='{"session_id":"smoke-test","hook_event_name":"SessionStart","cwd":"/tmp","source":"startup","model":"claude-sonnet-4-6","transcript_path":"/tmp/smoke.jsonl"}'

# UserPromptSubmit hooks (typically 1-4s due to pattern injection timeout)
test_hook "user-prompt-submit"            "${HOOKS_SCRIPTS}/user-prompt-submit.sh"          "$UPS_INPUT"     8
test_hook "user-prompt-delegation-rule"   "${HOOKS_SCRIPTS}/user-prompt-delegation-rule.sh"  "$UPS_INPUT"     8

# SessionStart hook — OMN-4566 regression: capability_probe.py must not emit to stdout
test_hook "session-start (OMN-4566 regression: no stdout pollution)" \
    "${HOOKS_SCRIPTS}/session-start.sh" \
    "$SESSION_INPUT" \
    12

echo
echo "────────────────────────────────────"
TOTAL=$(( PASS + FAIL ))
echo -e "Results: ${GREEN}${PASS} passed${RESET}, ${RED}${FAIL} failed${RESET} / ${TOTAL} total"
echo

if [[ "$FAIL" -gt 0 ]]; then
    echo -e "${RED}SMOKE TEST FAILED — do not deploy${RESET}"
    exit 1
fi

echo -e "${GREEN}All smoke tests passed${RESET}"
exit 0
