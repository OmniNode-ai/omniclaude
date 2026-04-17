#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# cron-overseer-verify.sh — Headless overseer-verify tick [OMN-9036]
#
# Thin wrapper that delegates to the canonical OVERSEER_VERIFY_PROMPT defined in
# setup-session-crons.sh via claude -p. No inline business logic — the prompt
# body instructs Claude to invoke node_overseer_verifier directly.
#
# The session skill currently has no --phase flag, so the overseer-verify tick
# is triggered by passing the literal prompt body (same pattern used by the
# session-bound CronCreate fallback in setup-session-crons.sh).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ONEX_REGISTRY_ROOT="${OMNI_HOME:-${ONEX_REGISTRY_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}}"
STATE_DIR="${ONEX_REGISTRY_ROOT}/.onex_state/overseer-verify-results"
LOG_DIR="/tmp/overseer-verify-logs"
PHASE_TIMEOUT=900
RUN_ID="overseer-verify-$(date -u +"%Y-%m-%dT%H-%M-%SZ")"
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

if [[ -f "${HOME}/.omnibase/.env" ]]; then
  # shellcheck disable=SC1091
  source "${HOME}/.omnibase/.env"
fi

export ONEX_RUN_ID="${RUN_ID}"
export ONEX_UNSAFE_ALLOW_EDITS=1

ALLOWED_TOOLS="Bash,Read,Write,Edit,Glob,Grep,mcp__linear-server__*"

preflight() {
  if ! command -v claude &>/dev/null; then
    echo "ERROR: claude CLI not found on PATH" >&2
    exit 1
  fi
}

preflight

mkdir -p "${STATE_DIR}" "${LOG_DIR}"

LOCK_DIR="${STATE_DIR}/cron-overseer-verify.lock.d"
LOCK_TIMEOUT=1800

if ! mkdir "${LOCK_DIR}" 2>/dev/null; then
  lock_time=$(stat -f %m "${LOCK_DIR}" 2>/dev/null || stat -c %Y "${LOCK_DIR}" 2>/dev/null || echo 0)
  now=$(date +%s)
  age=$(( now - lock_time ))
  if [[ ${age} -lt ${LOCK_TIMEOUT} ]]; then
    echo "SKIP: Previous invocation still running (lock age: ${age}s < ${LOCK_TIMEOUT}s)"
    exit 0
  fi
  echo "WARN: Stale lock detected (age: ${age}s). Removing."
  rm -rf "${LOCK_DIR}"
  if ! mkdir "${LOCK_DIR}" 2>/dev/null; then
    echo "SKIP: Lock re-acquired by another process after stale-cleanup"
    exit 0
  fi
fi

echo "pid=$$ started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${LOCK_DIR}/meta"
trap 'rm -rf "${LOCK_DIR}"' EXIT

log() {
  local msg
  msg="[cron-overseer-verify $(date -u +"%H:%M:%S")] $1"
  echo "${msg}"
  echo "${msg}" >> "${LOG_DIR}/${RUN_ID}.log"
}

log "=== overseer-verify tick ${RUN_ID} starting ==="

OUTPUT_FILE="${STATE_DIR}/${RUN_ID}.txt"

# Canonical prompt body, mirrored from setup-session-crons.sh OVERSEER_VERIFY_PROMPT.
# Keeping this literal instead of routing through a skill means there is exactly
# one source of truth for the overseer-verify instructions: this script + the
# session-cron bootstrap both paste the same text.
read -r -d '' PROMPT <<'PROMPT_BODY' || true
OVERSEER VERIFY + DISPATCH AUDIT — verify completed work AND check that the dispatch engine is working.

**Part 1 — Verify recent completions**
Check for PRs merged or tickets Done in the last hour. For each, run: uv run python -m omnimarket.nodes.node_overseer_verifier --ticket <id> or --pr <repo>#<num>. Report verdicts. ESCALATE → surface to user.

**Part 2 — Dispatch audit (the anti-passivity check)**
1. How many workers were spawned in the last hour? (Check TaskList for tasks created in last 60 min)
2. How many Linear tickets are In Progress or Todo with no active worker?
3. If gap > 0 (unworked tickets exist, no workers dispatched): THIS IS A FAILURE. Spawn workers for the gap NOW. Do not just report it.
4. Did any dispatched work use the dogfood path (node_dispatch_worker + local model)? Or all Claude agents? Log which.

This tick MUST end with: (a) all recent completions verified, (b) all unworked tickets either dispatched or explicitly blocked with reason.
PROMPT_BODY

if [[ "${DRY_RUN}" == "true" ]]; then
  log "[DRY RUN] Would execute: claude -p <overseer-verify prompt> --allowedTools '${ALLOWED_TOOLS}'"
  exit 0
fi

timeout_cmd=""
if command -v timeout &>/dev/null; then
  timeout_cmd="timeout ${PHASE_TIMEOUT}"
elif command -v gtimeout &>/dev/null; then
  timeout_cmd="gtimeout ${PHASE_TIMEOUT}"
fi

exit_code=0
${timeout_cmd} claude -p "${PROMPT}" \
  --print \
  --allowedTools "${ALLOWED_TOOLS}" \
  > "${OUTPUT_FILE}" 2>&1 || exit_code=$?

if [[ ${exit_code} -eq 124 ]]; then
  log "TIMEOUT: overseer-verify exceeded ${PHASE_TIMEOUT}s"
  exit 1
fi

if [[ ${exit_code} -ne 0 ]]; then
  log "FAILED: overseer-verify exited with code ${exit_code}"
  exit 1
fi

log "overseer-verify tick ${RUN_ID} complete"
exit 0
