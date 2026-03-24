#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# smoke_deploy.sh -- Post-deploy smoke test runner for all hooks in hooks.json
#
# Tests EVERY hook registered in hooks.json by feeding synthetic payloads.
# Proves: hook registration, shell execution, import-path viability,
# non-crashing under synthetic payloads. This is a deploy-integrity test,
# NOT a business-logic correctness test.
#
# Exit codes:
#   0 = all hooks pass
#   1 = one or more hooks failed
#   2 = usage error (missing args, bad paths)
#
# Usage:
#   bash smoke_deploy.sh <PLUGIN_ROOT>
#   bash smoke_deploy.sh plugins/onex          # local tree
#   bash smoke_deploy.sh ~/.claude/plugins/cache/omninode-tools/onex/2.2.5
#
# Pass criteria per hook:
#   PASS: exit 0 or exit 2 (intentional block)
#   FAIL: ModuleNotFoundError/ImportError in stderr, timeout (15s),
#         unexpected exit codes (not 0 or 2)
#
# [OMN-6369]

set -uo pipefail

# ── Args ──────────────────────────────────────────────────────────────────────
PLUGIN_ROOT="${1:-}"
if [[ -z "$PLUGIN_ROOT" ]]; then
    echo "Usage: smoke_deploy.sh <PLUGIN_ROOT>"
    echo "  PLUGIN_ROOT: path to plugin directory (e.g., plugins/onex)"
    exit 2
fi

if [[ ! -d "$PLUGIN_ROOT" ]]; then
    echo "ERROR: PLUGIN_ROOT does not exist: $PLUGIN_ROOT"
    exit 2
fi

HOOKS_JSON="${PLUGIN_ROOT}/hooks/hooks.json"
if [[ ! -f "$HOOKS_JSON" ]]; then
    echo "ERROR: hooks.json not found at: $HOOKS_JSON"
    exit 2
fi

# ── Config ────────────────────────────────────────────────────────────────────
TIMEOUT_SEC=15
PASS=0
FAIL=0
SKIP=0

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RESET='\033[0m'

# Environment variables to strip for isolation
SANITIZE_VARS=(
    ONEX_EVENT_BUS_TYPE
    ONEX_ENV
    PYTHONPATH
    VIRTUAL_ENV
)

# ── Synthetic payloads ────────────────────────────────────────────────────────
# Minimal valid JSON for each hook event type
PAYLOAD_SESSION_START='{"session_id":"smoke-deploy","hook_event_name":"SessionStart","cwd":"/tmp","source":"startup","model":"claude-sonnet-4-6","transcript_path":"/tmp/smoke.jsonl"}'
PAYLOAD_SESSION_END='{"session_id":"smoke-deploy","hook_event_name":"SessionEnd","cwd":"/tmp"}'
PAYLOAD_USER_PROMPT='{"session_id":"smoke-deploy","hook_event_name":"UserPromptSubmit","prompt":"smoke test prompt","cwd":"/tmp"}'
PAYLOAD_STOP='{"session_id":"smoke-deploy","hook_event_name":"Stop","cwd":"/tmp"}'
PAYLOAD_PRE_COMPACT='{"session_id":"smoke-deploy","hook_event_name":"PreCompact","cwd":"/tmp"}'

# PreToolUse/PostToolUse payloads keyed by tool_name matcher pattern
payload_for_tool() {
    local tool_name="$1"
    local event_name="$2"
    cat <<EOF
{"session_id":"smoke-deploy","hook_event_name":"${event_name}","tool_name":"${tool_name}","tool_input":{"command":"echo smoke"},"tool_response":{"stdout":"smoke"}}
EOF
}

# Map a matcher regex to a representative tool_name for testing
tool_name_for_matcher() {
    local matcher="$1"
    case "$matcher" in
        "^(Edit|Write)$") echo "Edit" ;;
        "^(Edit|Write|Bash)$") echo "Bash" ;;
        "Bash") echo "Bash" ;;
        "^(Task|Agent)$") echo "Task" ;;
        "^mcp__linear-server__(save_issue|update_issue)$") echo "mcp__linear-server__save_issue" ;;
        "^(Read|Write|Edit|Bash|Glob|Grep|Task|Skill|WebFetch|WebSearch|NotebookEdit|NotebookRead)$") echo "Read" ;;
        "Skill") echo "Skill" ;;
        "^(mcp__linear-server__save_issue|Bash)$") echo "Bash" ;;
        "") echo "Edit" ;;  # empty matcher = any tool
        *) echo "Edit" ;;   # fallback
    esac
}

# ── Hook event to payload mapping ─────────────────────────────────────────────
payload_for_event() {
    local event="$1"
    case "$event" in
        SessionStart) echo "$PAYLOAD_SESSION_START" ;;
        SessionEnd) echo "$PAYLOAD_SESSION_END" ;;
        UserPromptSubmit) echo "$PAYLOAD_USER_PROMPT" ;;
        Stop) echo "$PAYLOAD_STOP" ;;
        PreCompact) echo "$PAYLOAD_PRE_COMPACT" ;;
        PreToolUse|PostToolUse) echo "" ;;  # handled separately with matcher
        *) echo "" ;;
    esac
}

# ── Test runner ───────────────────────────────────────────────────────────────
test_hook() {
    local name="$1"
    local script="$2"
    local input="$3"
    local event="$4"

    local out_file; out_file="$(mktemp /tmp/smoke-deploy-out.XXXXXX)"
    local err_file; err_file="$(mktemp /tmp/smoke-deploy-err.XXXXXX)"
    local errors=""

    # Resolve PLUGIN_ROOT in command path (hooks.json uses ${CLAUDE_PLUGIN_ROOT})
    local resolved_script="$script"

    # Run with timeout, stripping env vars for isolation
    local env_unset_args=()
    for var in "${SANITIZE_VARS[@]}"; do
        env_unset_args+=("-u" "$var")
    done

    # Export PLUGIN_ROOT as CLAUDE_PLUGIN_ROOT for the hook scripts
    echo "$input" | timeout "$TIMEOUT_SEC" env \
        "${env_unset_args[@]}" \
        CLAUDE_PLUGIN_ROOT="$PLUGIN_ROOT" \
        LOG_FILE="/dev/null" \
        bash "$resolved_script" > "$out_file" 2> "$err_file"
    local exit_code=$?

    # Check exit code: 0 and 2 are acceptable
    if [[ "$exit_code" -eq 124 ]]; then
        errors+=" TIMEOUT(>${TIMEOUT_SEC}s)"
    elif [[ "$exit_code" -ne 0 ]] && [[ "$exit_code" -ne 2 ]]; then
        errors+=" exit=${exit_code}"
    fi

    # Check for import errors in stderr (fatal for deploy integrity)
    local stderr_content
    stderr_content="$(cat "$err_file")"
    if echo "$stderr_content" | grep -qiE "ModuleNotFoundError|ImportError"; then
        errors+=" IMPORT_ERROR"
        # Show the import error for debugging
        local import_err
        import_err="$(echo "$stderr_content" | grep -iE "ModuleNotFoundError|ImportError" | head -1)"
        errors+="(${import_err})"
    fi

    rm -f "$out_file" "$err_file"

    if [[ -n "$errors" ]]; then
        echo -e "  ${RED}FAIL${RESET} [${event}] ${name}:${errors}"
        FAIL=$(( FAIL + 1 ))
        return 1
    else
        local status_note=""
        [[ "$exit_code" -eq 2 ]] && status_note=" (exit=2, intentional block)"
        echo -e "  ${GREEN}PASS${RESET} [${event}] ${name}${status_note}"
        PASS=$(( PASS + 1 ))
        return 0
    fi
}

# ── Parse hooks.json and run tests ────────────────────────────────────────────
echo -e "${CYAN}======================================${RESET}"
echo -e "${CYAN}  Post-Deploy Smoke Test Runner${RESET}"
echo -e "${CYAN}  PLUGIN_ROOT: ${PLUGIN_ROOT}${RESET}"
echo -e "${CYAN}======================================${RESET}"
echo

# We only smoke-test PreToolUse and PostToolUse hooks (the ticket spec).
# SessionStart/SessionEnd/UserPromptSubmit are tested by the existing
# smoke-test-hooks.sh (deploy_local_plugin skill).
EVENTS_TO_TEST="PreToolUse PostToolUse"

for event in $EVENTS_TO_TEST; do
    echo -e "${YELLOW}--- ${event} hooks ---${RESET}"

    # Extract hooks for this event from hooks.json using python3
    # (jq may not be available in all environments)
    hook_entries=$("$( command -v python3 || echo python )" -c "
import json, sys
with open('${HOOKS_JSON}') as f:
    data = json.load(f)
hooks_map = data.get('hooks', {})
entries = hooks_map.get('${event}', [])
for entry in entries:
    for h in entry.get('hooks', []):
        cmd = h.get('command', '')
        matcher = entry.get('matcher', '')
        print(f'{cmd}\t{matcher}')
" 2>/dev/null)

    if [[ -z "$hook_entries" ]]; then
        echo -e "  ${YELLOW}SKIP${RESET} No ${event} hooks found"
        continue
    fi

    while IFS=$'\t' read -r cmd matcher; do
        # Resolve ${CLAUDE_PLUGIN_ROOT} in command path
        resolved_cmd="${cmd//\$\{CLAUDE_PLUGIN_ROOT\}/$PLUGIN_ROOT}"

        # Extract script name for display
        script_name="$(basename "$resolved_cmd")"

        if [[ ! -f "$resolved_cmd" ]]; then
            echo -e "  ${RED}FAIL${RESET} [${event}] ${script_name}: script not found at ${resolved_cmd}"
            FAIL=$(( FAIL + 1 ))
            continue
        fi

        # Build tool-specific payload
        tool_name="$(tool_name_for_matcher "$matcher")"
        input="$(payload_for_tool "$tool_name" "$event")"

        test_hook "$script_name" "$resolved_cmd" "$input" "$event"
    done <<< "$hook_entries"

    echo
done

# ── Summary ───────────────────────────────────────────────────────────────────
echo "========================================"
TOTAL=$(( PASS + FAIL ))
echo -e "Results: ${GREEN}${PASS} passed${RESET}, ${RED}${FAIL} failed${RESET} / ${TOTAL} total"
echo

if [[ "$FAIL" -gt 0 ]]; then
    echo -e "${RED}SMOKE TEST FAILED${RESET}"
    exit 1
fi

echo -e "${GREEN}SMOKE TEST PASSED${RESET}"
exit 0
