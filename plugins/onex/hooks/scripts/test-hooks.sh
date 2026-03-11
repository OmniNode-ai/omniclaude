#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Hook Test Harness
# Validates all hook scripts against their interface contract:
#   - Exit code 0
#   - Valid JSON on stdout
#   - No arithmetic errors or bash failures on stderr
#
# Usage: bash test-hooks.sh [--verbose]
#   --verbose  Print stdout/stderr for every test, not just failures

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOKS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

VERBOSE=0
[[ "${1:-}" == "--verbose" ]] && VERBOSE=1

# ─── Python discovery ────────────────────────────────────────────────────────
# Some hooks (user-prompt-submit.sh, post-tool-use-quality.sh) require Python.
# When running from the source tree, the .venv lives only in the deployed cache.
# Auto-discover it so tests pass without manual env setup.
if [[ -z "${PLUGIN_PYTHON_BIN:-}" ]]; then
    # 1. .venv co-located with this script's plugin root (deployed cache)
    _VENV_PYTHON="${HOOKS_DIR}/../lib/.venv/bin/python3"
    # 2. Deployed cache fallback (when running from source worktree)
    _CACHE_PYTHON="$HOME/.claude/plugins/cache/omninode-tools/onex/2.2.5/lib/.venv/bin/python3"
    if [[ -x "$_VENV_PYTHON" ]]; then
        export PLUGIN_PYTHON_BIN="$_VENV_PYTHON"
    elif [[ -x "$_CACHE_PYTHON" ]]; then
        export PLUGIN_PYTHON_BIN="$_CACHE_PYTHON"
    fi
    unset _VENV_PYTHON _CACHE_PYTHON
fi

PASS=0
FAIL=0

# ─── helpers ───────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RESET='\033[0m'

pass() { echo -e "  ${GREEN}PASS${RESET} $1"; (( PASS++ )) || true; }
fail() { echo -e "  ${RED}FAIL${RESET} $1"; (( FAIL++ )) || true; }
section() { echo; echo -e "${YELLOW}── $1 ──${RESET}"; }

# run_test <label> <script_path> <json_input> [<jq_assertion>]
#
# jq_assertion: a jq filter that must produce "true" on stdout, e.g.
#   '.hookSpecificOutput.hookEventName == "UserPromptSubmit"'
run_test() {
    local label="$1"
    local script="$2"
    local input="$3"
    local assertion="${4:-}"

    local out_file; out_file="$(mktemp /tmp/hook-test-out.XXXXXX)"
    local err_file; err_file="$(mktemp /tmp/hook-test-err.XXXXXX)"

    bash "$script" < <(echo "$input") > "$out_file" 2> "$err_file"
    local exit_code=$?

    local errors=""

    # 1. Exit code must be 0
    [[ "$exit_code" -ne 0 ]] && errors+=" exit=${exit_code}"

    # 2. Stdout must be valid JSON
    if ! jq -e . "$out_file" >/dev/null 2>&1; then
        errors+=" invalid-json"
    fi

    # 3. Stderr must not contain known failure patterns
    if grep -qE "value too great for base|arithmetic|unbound variable|command not found" "$err_file" 2>/dev/null; then
        errors+=" stderr-errors"
    fi

    # 4. Optional jq assertion
    if [[ -n "$assertion" ]] && [[ -z "$errors" ]]; then
        local result
        result="$(jq -r "$assertion" "$out_file" 2>/dev/null)"
        [[ "$result" != "true" ]] && errors+=" assertion-failed(got:${result})"
    fi

    if [[ -n "$errors" ]]; then
        fail "${label}${errors}"
        if [[ "$VERBOSE" -eq 1 ]] || true; then
            echo "       script: $script"
            echo "       input:  $input"
            [[ -s "$err_file" ]] && echo "       stderr: $(cat "$err_file" | head -3)"
            [[ -s "$out_file" ]] && echo "       stdout: $(head -c 200 "$out_file")"
        fi
    else
        pass "$label"
        if [[ "$VERBOSE" -eq 1 ]]; then
            [[ -s "$err_file" ]] && echo "       stderr: $(cat "$err_file" | head -2)"
        fi
    fi

    rm -f "$out_file" "$err_file"
}

# ─── test data ──────────────────────────────────────────────────────────────

USER_PROMPT_INPUT='{"session_id":"test-abc-123","hook_event_name":"UserPromptSubmit","prompt":"write some code for me"}'
USER_PROMPT_CONVERSATIONAL='{"session_id":"test-abc-123","hook_event_name":"UserPromptSubmit","prompt":"what time is it?"}'

POST_BASH_INPUT='{"session_id":"test-abc-123","tool_name":"Bash","tool_input":{"command":"gh pr list --repo OmniNode-ai/omniclaude"},"tool_response":{"output":"5 results"}}'
POST_BASH_COMMIT_INPUT='{"session_id":"test-abc-123","tool_name":"Bash","tool_input":{"command":"git commit -m chore: update deps"},"tool_response":{"output":"1 file changed"}}'
POST_READ_INPUT='{"session_id":"test-abc-123","tool_name":"Read","tool_input":{"file_path":"/tmp/test.py"},"tool_response":{"output":"content"}}'
POST_WRITE_INPUT='{"session_id":"test-abc-123","tool_name":"Write","tool_input":{"file_path":"/tmp/test.py"},"tool_response":{"output":"written"}}'
POST_AGENT_INPUT='{"session_id":"test-abc-123","tool_name":"Task","tool_input":{},"tool_response":{"output":"done"}}'

SESSION_START_INPUT='{"session_id":"test-abc-123","hook_event_name":"SessionStart","cwd":"/tmp","source":"startup","model":"claude-sonnet-4-6","transcript_path":"/tmp/test.jsonl"}'

# ─── SessionStart hooks ──────────────────────────────────────────────────────

section "SessionStart: session-start.sh"

# Regression test for OMN-4566: capability_probe.py used to print "tier=event_bus" to stdout,
# which prepended to the JSON output and broke Claude Code's hook JSON parser.
# This test catches that class of bug: stdout must start with '{' (be pure JSON).
run_test "startup → valid JSON output (no stdout pollution)" \
    "${SCRIPT_DIR}/session-start.sh" \
    "$SESSION_START_INPUT" \
    '.hookSpecificOutput.hookEventName == "SessionStart"'

run_test "startup → stdout does not contain tier= (regression: OMN-4566)" \
    "${SCRIPT_DIR}/session-start.sh" \
    "$SESSION_START_INPUT"
# Note: the second test validates JSON-only stdout via the run_test framework's
# jq parse check — any "tier=..." prefix would fail the JSON parse check.

# ─── UserPromptSubmit hooks ──────────────────────────────────────────────────

section "UserPromptSubmit: user-prompt-submit.sh"
run_test "work prompt → exits 0" \
    "${SCRIPT_DIR}/user-prompt-submit.sh" \
    "$USER_PROMPT_INPUT" \
    '.hookSpecificOutput.hookEventName == "UserPromptSubmit"'

run_test "conversational prompt → exits 0" \
    "${SCRIPT_DIR}/user-prompt-submit.sh" \
    "$USER_PROMPT_CONVERSATIONAL" \
    '.hookSpecificOutput.hookEventName == "UserPromptSubmit"'

run_test "malformed JSON → exits 0 (fallback)" \
    "${SCRIPT_DIR}/user-prompt-submit.sh" \
    'not-json'

section "UserPromptSubmit: user-prompt-delegation-rule.sh"
run_test "work prompt → delegation rule injected" \
    "${SCRIPT_DIR}/user-prompt-delegation-rule.sh" \
    "$USER_PROMPT_INPUT" \
    '.hookSpecificOutput.additionalContext | contains("DELEGATION RULE")'

run_test "no session_id → exits 0" \
    "${SCRIPT_DIR}/user-prompt-delegation-rule.sh" \
    '{"hook_event_name":"UserPromptSubmit","prompt":"hello"}'

# ─── PostToolUse hooks ───────────────────────────────────────────────────────

section "PostToolUse: post-tool-delegation-counter.sh"
run_test "Bash call → pass-through (below threshold)" \
    "${SCRIPT_DIR}/post-tool-delegation-counter.sh" \
    "$POST_BASH_INPUT"

run_test "Agent/Task call → marks delegated, pass-through" \
    "${SCRIPT_DIR}/post-tool-delegation-counter.sh" \
    "$POST_AGENT_INPUT"

run_test "Read call → pass-through or warning JSON" \
    "${SCRIPT_DIR}/post-tool-delegation-counter.sh" \
    "$POST_READ_INPUT"

section "PostToolUse: post-tool-use-ci-reminder.sh"
run_test "non-commit Bash → pass-through unchanged" \
    "${HOOKS_DIR}/post-tool-use-ci-reminder.sh" \
    "$POST_BASH_INPUT"

run_test "git commit Bash → CI reminder injected" \
    "${HOOKS_DIR}/post-tool-use-ci-reminder.sh" \
    "$POST_BASH_COMMIT_INPUT" \
    '.hookSpecificOutput.additionalContext | contains("CI Reminder")'

section "PostToolUse: post-tool-use-quality.sh"
run_test "Read tool → exits 0" \
    "${SCRIPT_DIR}/post-tool-use-quality.sh" \
    "$POST_READ_INPUT"

run_test "Bash tool → exits 0" \
    "${SCRIPT_DIR}/post-tool-use-quality.sh" \
    "$POST_BASH_INPUT"

# ─── summary ────────────────────────────────────────────────────────────────

echo
echo "────────────────────────────────────"
TOTAL=$(( PASS + FAIL ))
echo -e "Results: ${GREEN}${PASS} passed${RESET}, ${RED}${FAIL} failed${RESET} / ${TOTAL} total"

[[ "$FAIL" -eq 0 ]] && exit 0 || exit 1
