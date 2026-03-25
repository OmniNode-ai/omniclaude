#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Nightly Merge Sweep — Headless Mode
# Runs Claude Code in headless mode (claude -p) across all repos for
# unattended nightly merge sweeps. Produces per-repo JSON records.
#
# Ticket: OMN-6531
# Usage:  ./scripts/nightly-merge-sweep.sh [--timeout MINUTES] [--repos REPO1,REPO2]

set -euo pipefail

# -----------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------
OMNI_HOME="${OMNI_HOME:-/Volumes/PRO-G40/Code/omni_home}"  # local-path-ok
DEFAULT_REPOS="omniclaude,omnibase_core,omnibase_infra,omnibase_spi,omniintelligence,omnimemory,omnidash,omninode_infra,omniweb,onex_change_control"
TIMEOUT_MINUTES="${NIGHTLY_SWEEP_TIMEOUT_MINUTES:-15}"
LOG_DIR="${HOME}/.claude/nightly-sweep"
DATE_STAMP=$(date -u +"%Y-%m-%d")
LOCK_FILE="${LOG_DIR}/nightly-sweep.lock"
OUTPUT_DIR="${LOG_DIR}/${DATE_STAMP}"

# Allowed tools for headless mode
ALLOWED_TOOLS="Bash,Read,Edit,Write,Glob,Grep,Skill,mcp__linear-server__save_issue,mcp__linear-server__list_issues,mcp__linear-server__get_issue"

# -----------------------------------------------------------------------
# Parse arguments
# -----------------------------------------------------------------------
REPOS_CSV="$DEFAULT_REPOS"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --timeout)
            TIMEOUT_MINUTES="$2"
            shift 2
            ;;
        --repos)
            REPOS_CSV="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [--timeout MINUTES] [--repos REPO1,REPO2,...]"
            echo ""
            echo "Options:"
            echo "  --timeout N   Per-repo timeout in minutes (default: 15)"
            echo "  --repos CSV   Comma-separated list of repos (default: all)"
            echo ""
            echo "Environment:"
            echo "  OMNI_HOME                     Path to omni_home (default: /Volumes/PRO-G40/Code/omni_home)"  # local-path-ok
            echo "  NIGHTLY_SWEEP_TIMEOUT_MINUTES  Per-repo timeout (default: 15)"
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 1
            ;;
    esac
done

IFS=',' read -ra REPOS <<< "$REPOS_CSV"

# -----------------------------------------------------------------------
# Lock: prevent overlapping runs
# -----------------------------------------------------------------------
mkdir -p "$LOG_DIR" "$OUTPUT_DIR"

if [[ -f "$LOCK_FILE" ]]; then
    LOCK_PID=$(cat "$LOCK_FILE" 2>/dev/null)
    if kill -0 "$LOCK_PID" 2>/dev/null; then
        echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] ERROR: Another nightly sweep is running (PID $LOCK_PID). Aborting." >&2
        exit 1
    else
        echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] WARNING: Stale lock file found (PID $LOCK_PID not running). Removing." >&2
        rm -f "$LOCK_FILE"
    fi
fi

echo "$$" > "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"' EXIT

# -----------------------------------------------------------------------
# Verify claude CLI is available
# -----------------------------------------------------------------------
if ! command -v claude >/dev/null 2>&1; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] ERROR: claude CLI not found in PATH." >&2
    exit 1
fi

# -----------------------------------------------------------------------
# Run sweep per repo
# -----------------------------------------------------------------------
SUCCEEDED=0
FAILED=0
SKIPPED=0
TOTAL=${#REPOS[@]}

echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Starting nightly merge sweep: ${TOTAL} repos, ${TIMEOUT_MINUTES}m timeout each"

for repo in "${REPOS[@]}"; do
    REPO_PATH="${OMNI_HOME}/${repo}"
    REPO_LOG="${OUTPUT_DIR}/${repo}.json"
    REPO_START=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

    echo "[${REPO_START}] Processing: ${repo}"

    # Check if repo exists
    if [[ ! -d "$REPO_PATH" ]]; then
        echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] SKIP: ${repo} not found at ${REPO_PATH}"
        printf '{"repo":"%s","status":"skipped","reason":"repo_not_found","started_at":"%s","completed_at":"%s"}\n' \
            "$repo" "$REPO_START" "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" > "$REPO_LOG"
        SKIPPED=$((SKIPPED + 1))
        continue
    fi

    # Run claude -p with timeout
    TIMEOUT_SECONDS=$((TIMEOUT_MINUTES * 60))

    set +e
    RESULT=$(timeout "${TIMEOUT_SECONDS}" claude -p \
        "Run /onex:merge_sweep for ${repo}. Check for open PRs that can be merged, fix CI failures, and clean up stale branches." \
        --allowedTools "$ALLOWED_TOOLS" \
        --output-format json \
        2>"${OUTPUT_DIR}/${repo}.stderr" \
        < /dev/null)
    EXIT_CODE=$?
    set -e

    REPO_END=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

    if [[ $EXIT_CODE -eq 124 ]]; then
        # Timeout
        echo "[${REPO_END}] TIMEOUT: ${repo} exceeded ${TIMEOUT_MINUTES}m"
        printf '{"repo":"%s","status":"timeout","exit_code":124,"timeout_minutes":%d,"started_at":"%s","completed_at":"%s"}\n' \
            "$repo" "$TIMEOUT_MINUTES" "$REPO_START" "$REPO_END" > "$REPO_LOG"
        FAILED=$((FAILED + 1))
    elif [[ $EXIT_CODE -eq 0 ]]; then
        echo "[${REPO_END}] SUCCESS: ${repo}"
        # Write the JSON result directly
        if [[ -n "$RESULT" ]]; then
            printf '%s\n' "$RESULT" | jq --arg repo "$repo" --arg start "$REPO_START" --arg end "$REPO_END" \
                '. + {"repo": $repo, "status": "success", "started_at": $start, "completed_at": $end}' \
                > "$REPO_LOG" 2>/dev/null \
                || printf '{"repo":"%s","status":"success","exit_code":0,"started_at":"%s","completed_at":"%s","raw_output_length":%d}\n' \
                    "$repo" "$REPO_START" "$REPO_END" "${#RESULT}" > "$REPO_LOG"
        else
            printf '{"repo":"%s","status":"success","exit_code":0,"started_at":"%s","completed_at":"%s","raw_output_length":0}\n' \
                "$repo" "$REPO_START" "$REPO_END" > "$REPO_LOG"
        fi
        SUCCEEDED=$((SUCCEEDED + 1))
    else
        echo "[${REPO_END}] FAILED: ${repo} (exit ${EXIT_CODE})"

        # Check for rate limit (429) or auth failure (401) in stderr
        STDERR_CONTENT=$(cat "${OUTPUT_DIR}/${repo}.stderr" 2>/dev/null || echo "")
        FAILURE_CLASS="unknown"
        if echo "$STDERR_CONTENT" | grep -qi "rate.limit\|429\|too many requests"; then
            FAILURE_CLASS="rate_limit"
        elif echo "$STDERR_CONTENT" | grep -qi "unauthorized\|401\|auth"; then
            FAILURE_CLASS="auth_failure"
        fi

        printf '{"repo":"%s","status":"failed","exit_code":%d,"failure_class":"%s","started_at":"%s","completed_at":"%s"}\n' \
            "$repo" "$EXIT_CODE" "$FAILURE_CLASS" "$REPO_START" "$REPO_END" > "$REPO_LOG"
        FAILED=$((FAILED + 1))

        # Back off on rate limit
        if [[ "$FAILURE_CLASS" == "rate_limit" ]]; then
            echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Rate limited. Waiting 60s before next repo."
            sleep 60
        fi
    fi
done

# -----------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------
SUMMARY_FILE="${OUTPUT_DIR}/summary.json"
printf '{"date":"%s","total":%d,"succeeded":%d,"failed":%d,"skipped":%d,"timeout_minutes":%d}\n' \
    "$DATE_STAMP" "$TOTAL" "$SUCCEEDED" "$FAILED" "$SKIPPED" "$TIMEOUT_MINUTES" > "$SUMMARY_FILE"

echo ""
echo "=============================="
echo "Nightly Merge Sweep Summary"
echo "=============================="
echo "Date:      ${DATE_STAMP}"
echo "Total:     ${TOTAL}"
echo "Succeeded: ${SUCCEEDED}"
echo "Failed:    ${FAILED}"
echo "Skipped:   ${SKIPPED}"
echo "Output:    ${OUTPUT_DIR}/"
echo ""

# Exit with failure if any repos failed
if [[ $FAILED -gt 0 ]]; then
    exit 1
fi
exit 0
