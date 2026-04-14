#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# PreToolUse Hostile Review Gate [OMN-8702]
#
# Hard-blocks gh pr merge / enqueuePullRequest unless hostile_reviewer has
# produced a passing result for the PR being merged.
#
# Pass conditions (exit 0):
#   - Tool is not Bash
#   - Bash command is not a merge/enqueue operation
#   - Kill switch HOSTILE_REVIEW_GATE_DISABLED=1
#   - Lite mode
#   - ONEX_STATE_DIR not set (fail open)
#   - Hostile review pass evidence found for this PR
#
# Block condition (exit 2):
#   - gh pr merge or enqueuePullRequest called, no pass evidence for this PR
#
# Evidence checked (first match wins):
#   1. $ONEX_STATE_DIR/hostile-review-pass/<pr_num>.json  (sentinel written by skill)
#   2. $ONEX_STATE_DIR/skill-results/*/hostile-reviewer.json  with matching pr + clean verdict
#
# Ticket: OMN-8702

set -euo pipefail

_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"
source "$(dirname "${BASH_SOURCE[0]}")/error-guard.sh" 2>/dev/null || true

if [[ "${OMNICLAUDE_HOOKS_DISABLED:-0}" == "1" ]]; then cat; exit 0; fi
if [[ "${HOSTILE_REVIEW_GATE_DISABLED:-0}" == "1" ]]; then cat; exit 0; fi

# --- Lite mode guard ---
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_MODE_SH="${_SCRIPT_DIR}/../../lib/mode.sh"
if [[ -f "$_MODE_SH" ]]; then source "$_MODE_SH"; [[ "$(omniclaude_mode)" == "lite" ]] && { cat; exit 0; }; fi
unset _SCRIPT_DIR _MODE_SH

cd "$HOME" 2>/dev/null || cd /tmp || true

source "$(dirname "${BASH_SOURCE[0]}")/onex-paths.sh" 2>/dev/null || true
LOG_FILE="${ONEX_STATE_DIR:-/tmp}/hooks/logs/hostile-review-gate.log"
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

if ! command -v jq >/dev/null 2>&1; then cat; exit 0; fi

TOOL_INFO=$(cat)

# Only intercept Bash tool
TOOL_NAME=$(printf '%s' "$TOOL_INFO" | jq -r '.tool_name // ""' 2>/dev/null || true)
if [[ "$TOOL_NAME" != "Bash" ]]; then
    printf '%s\n' "$TOOL_INFO"
    exit 0
fi

COMMAND=$(printf '%s' "$TOOL_INFO" | jq -r '.tool_input.command // ""' 2>/dev/null || true)

# Gate: only fire on merge/enqueue operations
is_merge_op=false
if echo "$COMMAND" | grep -qE 'gh pr merge|enqueuePullRequest'; then
    is_merge_op=true
fi

if [[ "$is_merge_op" == "false" ]]; then
    printf '%s\n' "$TOOL_INFO"
    exit 0
fi

# Fail open if state dir not configured
if [[ -z "${ONEX_STATE_DIR:-}" ]]; then
    printf '%s\n' "$TOOL_INFO"
    exit 0
fi

# Extract PR number from command (best-effort)
PR_NUM=""
if echo "$COMMAND" | grep -qE 'gh pr merge [0-9]+'; then
    PR_NUM=$(echo "$COMMAND" | grep -oE 'gh pr merge [0-9]+' | grep -oE '[0-9]+$' | head -1)
elif echo "$COMMAND" | grep -qE '"pullRequestId"\s*:\s*"[^"]+"'; then
    PR_NUM=$(echo "$COMMAND" | grep -oE '"pullRequestId"\s*:\s*"[^"]+"' | grep -oE '"[^"]+"\s*$' | tr -d '"' | xargs | head -1)
fi

# Check sentinel file (written by hostile_reviewer skill after gate-mode pass)
SENTINEL_DIR="${ONEX_STATE_DIR}/hostile-review-pass"
if [[ -n "$PR_NUM" && -f "${SENTINEL_DIR}/${PR_NUM}.json" ]]; then
    SENTINEL_AGE=$(( $(date +%s) - $(date -r "${SENTINEL_DIR}/${PR_NUM}.json" +%s 2>/dev/null || echo 0) ))
    # Accept sentinels written within 24 hours
    if [[ $SENTINEL_AGE -lt 86400 ]]; then
        printf '%s\n' "$TOOL_INFO"
        exit 0
    fi
fi

# Check skill-results artifacts for this PR
RESULTS_DIR="${ONEX_STATE_DIR}/skill-results"
if [[ -d "$RESULTS_DIR" && -n "$PR_NUM" ]]; then
    while IFS= read -r -d '' result_file; do
        verdict=$(jq -r '.overall_verdict // ""' "$result_file" 2>/dev/null || true)
        extra_status=$(jq -r '.extra_status // ""' "$result_file" 2>/dev/null || true)
        target=$(jq -r '.target // ""' "$result_file" 2>/dev/null || true)

        # Match PR number in target field
        if [[ "$target" == "$PR_NUM" || "$target" == *"/$PR_NUM" ]]; then
            if [[ "$verdict" == "clean" || "$verdict" == "pass" || "$extra_status" == "passed" ]]; then
                printf '%s\n' "$TOOL_INFO"
                exit 0
            fi
        fi
    done < <(find "$RESULTS_DIR" -name "hostile-reviewer.json" -newer /tmp -print0 2>/dev/null || true)

    # Broader search: any recent result matching PR (not requiring target match, accept clean verdict)
    while IFS= read -r -d '' result_file; do
        verdict=$(jq -r '.overall_verdict // ""' "$result_file" 2>/dev/null || true)
        extra_status=$(jq -r '.extra_status // ""' "$result_file" 2>/dev/null || true)
        file_age=$(( $(date +%s) - $(date -r "$result_file" +%s 2>/dev/null || echo 0) ))

        # Accept any clean result written in the last 2 hours (session-scoped)
        if [[ $file_age -lt 7200 ]]; then
            if [[ "$verdict" == "clean" || "$verdict" == "pass" || "$extra_status" == "passed" ]]; then
                printf '%s\n' "$TOOL_INFO"
                exit 0
            fi
        fi
    done < <(find "$RESULTS_DIR" -name "hostile-reviewer.json" -print0 2>/dev/null || true)
fi

# No pass evidence found — block
PR_DISPLAY="${PR_NUM:-<unknown>}"
printf '[hostile-review-gate] BLOCKED merge on PR %s: no hostile_reviewer pass evidence found.\n' "$PR_DISPLAY" >> "$LOG_FILE" 2>/dev/null || true

printf 'Merge blocked [OMN-8702]: hostile_reviewer has not produced a passing review for PR %s.\nRun: /onex:hostile_reviewer --pr %s --repo <owner/repo> --gate\nThen retry the merge.\n' \
    "$PR_DISPLAY" "$PR_DISPLAY" >&2

exit 2
