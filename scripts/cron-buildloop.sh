#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# DEPRECATED: cron-buildloop.sh — Build loop is now integrated into cron-closeout.sh
# as phases F1-F3. Use cron-closeout.sh instead:
#
#   ./scripts/cron-closeout.sh              # Full pipeline (close-out + build)
#   ./scripts/cron-closeout.sh --build-only # Build loop only (phases F1-F3)
#   ./scripts/cron-closeout.sh --skip-build # Close-out only (no build)
#
# This script is kept for backwards compatibility but will be removed in a future release.
# The launchd plist ai.omninode.buildloop.plist should be unloaded:
#   launchctl unload ~/Library/LaunchAgents/ai.omninode.buildloop.plist
#   rm ~/Library/LaunchAgents/ai.omninode.buildloop.plist
#
# Original: Headless build loop scheduler using claude -p
# Requires: claude CLI (uses OAuth, NOT ANTHROPIC_API_KEY)

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OMNI_HOME="${OMNI_HOME:-/Users/jonah/Code/omni_home}"  # local-path-ok: script runs on local machine only
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"
STATE_DIR="${OMNI_HOME}/.onex_state/autopilot"
LOG_DIR="/tmp/buildloop-logs"
MAX_CYCLES=3
PHASE_TIMEOUT=1800  # 30 minutes per build-loop invocation
RUN_ID="buildloop-$(date -u +"%Y-%m-%dT%H-%M-%SZ")"
RUN_DIR="${STATE_DIR}/runs/${RUN_ID}"
DRY_RUN=false
ENABLE_DELEGATION=true

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    --max-cycles) MAX_CYCLES="$2"; shift 2 ;;
    --no-delegation) ENABLE_DELEGATION=false; shift ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

# Source credentials
if [[ -f "${HOME}/.omnibase/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${HOME}/.omnibase/.env"
  set +a
fi

export ONEX_RUN_ID="${RUN_ID}"
export ONEX_UNSAFE_ALLOW_EDITS=1

# ---------------------------------------------------------------------------
# Delegation configuration
# ---------------------------------------------------------------------------
# When delegation is enabled, the build loop's ticket-pipeline invocations
# will route delegatable tasks (testing, documentation, research) to local
# models via the delegation orchestrator instead of frontier Claude.

if [[ "${ENABLE_DELEGATION}" == "true" ]]; then
  export ENABLE_LOCAL_INFERENCE_PIPELINE=true
  export ENABLE_LOCAL_DELEGATION=true
fi

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

preflight() {
  local missing=()

  if ! command -v claude &>/dev/null; then
    missing+=("claude CLI")
  fi

  # Note: claude -p uses its own auth (Claude Code login), not ANTHROPIC_API_KEY

  if [[ ${#missing[@]} -gt 0 ]]; then
    echo "ERROR: Missing requirements: ${missing[*]}" >&2
    exit 1
  fi
}

preflight

# ---------------------------------------------------------------------------
# Delegation health pre-check [OMN-7391]
# ---------------------------------------------------------------------------
# Before enabling delegation, verify local LLMs respond on their
# OpenAI-compatible /v1/models endpoints. If either is unreachable,
# disable delegation gracefully (build loop continues with frontier only).

check_delegation_health() {
  if [[ "${ENABLE_DELEGATION}" != "true" ]]; then
    return 0
  fi

  local coder_url="${LLM_CODER_URL:-}"
  local fast_url="${LLM_CODER_FAST_URL:-}"
  local failures=()

  if [[ -z "${coder_url}" && -z "${fast_url}" ]]; then
    echo "WARN: Delegation enabled but LLM_CODER_URL and LLM_CODER_FAST_URL not set. Disabling delegation."
    ENABLE_DELEGATION=false
    export ENABLE_LOCAL_INFERENCE_PIPELINE=false
    export ENABLE_LOCAL_DELEGATION=false
    return 0
  fi

  # Probe each endpoint with a 5s timeout
  if [[ -n "${coder_url}" ]]; then
    if curl -sf --max-time 5 "${coder_url}/v1/models" >/dev/null 2>&1; then
      echo "Delegation health: ${coder_url} OK"
    else
      failures+=("LLM_CODER_URL (${coder_url})")
    fi
  fi

  if [[ -n "${fast_url}" ]]; then
    if curl -sf --max-time 5 "${fast_url}/v1/models" >/dev/null 2>&1; then
      echo "Delegation health: ${fast_url} OK"
    else
      failures+=("LLM_CODER_FAST_URL (${fast_url})")
    fi
  fi

  if [[ ${#failures[@]} -gt 0 ]]; then
    echo "WARN: Delegation endpoints unreachable: ${failures[*]}"
    echo "WARN: Disabling delegation for this run. Build loop will use frontier Claude only."
    ENABLE_DELEGATION=false
    export ENABLE_LOCAL_INFERENCE_PIPELINE=false
    export ENABLE_LOCAL_DELEGATION=false
  fi
}

check_delegation_health

# ---------------------------------------------------------------------------
# Directory setup
# ---------------------------------------------------------------------------

mkdir -p "${STATE_DIR}" "${RUN_DIR}" "${LOG_DIR}"

# Ensure friction directory exists for build loop friction events
FRICTION_DIR="${ONEX_STATE_DIR:-${OMNI_HOME}/.onex_state}/friction"
mkdir -p "${FRICTION_DIR}"

# ---------------------------------------------------------------------------
# Log rotation — keep last 20 logs
# ---------------------------------------------------------------------------

rotate_logs() {
  local count
  count=$(find "${LOG_DIR}" -name "buildloop-*.log" -type f 2>/dev/null | wc -l)
  if [[ ${count} -gt 20 ]]; then
    find "${LOG_DIR}" -name "buildloop-*.log" -type f -printf '%T+ %p\n' 2>/dev/null \
      | sort | head -n $(( count - 20 )) | cut -d' ' -f2- | xargs rm -f 2>/dev/null || true
    # macOS fallback (no -printf)
    ls -1t "${LOG_DIR}"/buildloop-*.log 2>/dev/null | tail -n +21 | xargs rm -f 2>/dev/null || true
  fi
}

rotate_logs

# ---------------------------------------------------------------------------
# Lock directory — atomic, prevents concurrent runs
# ---------------------------------------------------------------------------

LOCK_DIR="${STATE_DIR}/cron-buildloop.lock"
LOCK_TIMEOUT=3600  # 60 minutes

if [[ -d "${LOCK_DIR}" ]]; then
  lock_file="${LOCK_DIR}/pid"
  if [[ -f "${lock_file}" ]]; then
    lock_time=$(stat -f %m "${lock_file}" 2>/dev/null || stat -c %Y "${lock_file}" 2>/dev/null || echo 0)
    now=$(date +%s)
    age=$(( now - lock_time ))

    if [[ ${age} -lt ${LOCK_TIMEOUT} ]]; then
      echo "SKIP: Previous build loop still running (lock age: ${age}s < ${LOCK_TIMEOUT}s)"
      exit 0
    else
      echo "WARN: Stale lock detected (age: ${age}s). Removing."
      rm -rf "${LOCK_DIR}"
    fi
  else
    rm -rf "${LOCK_DIR}"
  fi
fi

if ! mkdir "${LOCK_DIR}" 2>/dev/null; then
  echo "SKIP: Could not acquire lock (concurrent run)"
  exit 0
fi

echo "pid=$$ started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${LOCK_DIR}/pid"

# ---------------------------------------------------------------------------
# Watchdog state integration
# ---------------------------------------------------------------------------

WATCHDOG_PHASE="starting"
WATCHDOG_EXIT_CODE=0
WATCHDOG_SCRIPT="$(dirname "$0")/watchdog-state-write.sh"

cleanup_and_record() {
  local exit_code="${WATCHDOG_EXIT_CODE:-$?}"
  rm -rf "${LOCK_DIR}"
  if [[ -x "${WATCHDOG_SCRIPT}" ]]; then
    if [[ ${exit_code} -eq 0 ]]; then
      "${WATCHDOG_SCRIPT}" buildloop pass complete "" 2>/dev/null || true
    else
      "${WATCHDOG_SCRIPT}" buildloop fail "${WATCHDOG_PHASE}" "exit_code=${exit_code}" 2>/dev/null || true
    fi
  fi
}

trap 'cleanup_and_record' EXIT

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

log() {
  local msg="[cron-buildloop $(date -u +"%H:%M:%S")] $1"
  echo "${msg}"
  echo "${msg}" >> "${LOG_DIR}/${RUN_ID}.log"
}

# Emit a friction event to the NDJSON registry (best-effort)
emit_friction() {
  local severity="$1"
  local description="$2"
  local error_msg="${3:-}"
  local ts
  ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  local record
  record=$(cat <<EOJSON
{"skill":"cron_buildloop","surface":"cron_buildloop/exit","severity":"${severity}","description":"${description}","error_message":"${error_msg}","correlation_id":"${RUN_ID}","phase":"cron","timestamp":"${ts}"}
EOJSON
)
  echo "${record}" >> "${FRICTION_DIR}/build-loop.ndjson" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# Main execution
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Watchdog pre-check — enforce escalation policy before starting
# ---------------------------------------------------------------------------

WATCHDOG_CHECK="$(dirname "$0")/watchdog-check.sh"
if [[ -x "${WATCHDOG_CHECK}" ]]; then
  WATCHDOG_RESULT=$("${WATCHDOG_CHECK}" buildloop 2>/dev/null) || true
  WATCHDOG_ACTION=$(echo "${WATCHDOG_RESULT}" | jq -r '.action // "restart"' 2>/dev/null || echo "restart")
  WATCHDOG_LEVEL=$(echo "${WATCHDOG_RESULT}" | jq -r '.level // 0' 2>/dev/null || echo "0")

  if [[ "${WATCHDOG_ACTION}" == "alert_user" ]]; then
    echo "WATCHDOG BLOCK: Escalation level ${WATCHDOG_LEVEL}. Not restarting."
    echo "Run: $(dirname "$0")/watchdog-state-read.sh buildloop"
    echo "To reset after fixing: rm ${OMNI_HOME}/.onex_state/watchdog/loop-health.json"
    WATCHDOG_PHASE="watchdog_block"; WATCHDOG_EXIT_CODE=5; exit 5
  fi

  if [[ "${WATCHDOG_ACTION}" != "restart" ]]; then
    log "WATCHDOG: Escalation level ${WATCHDOG_LEVEL}, action=${WATCHDOG_ACTION}"
  fi
fi

log "=== Build loop run ${RUN_ID} starting ==="
log "Max cycles: ${MAX_CYCLES}"
log "Delegation: ${ENABLE_DELEGATION}"
log "State dir: ${RUN_DIR}"

if [[ "${DRY_RUN}" == "true" ]]; then
  log "[DRY RUN] Would execute: claude -p '/build-loop --max-cycles ${MAX_CYCLES}' --allowedTools '...'"
  log "[DRY RUN] ENABLE_LOCAL_DELEGATION=${ENABLE_LOCAL_DELEGATION:-false}"
  log "[DRY RUN] ENABLE_LOCAL_INFERENCE_PIPELINE=${ENABLE_LOCAL_INFERENCE_PIPELINE:-false}"
  log "Dry run complete."
  exit 0
fi

OUTPUT_FILE="${RUN_DIR}/build-loop-output.txt"

log "Starting claude -p invocation with ${PHASE_TIMEOUT}s timeout"

exit_code=0
# Use gtimeout (GNU) if available, fall back to no timeout on macOS
timeout_cmd=""
if command -v timeout &>/dev/null; then timeout_cmd="timeout ${PHASE_TIMEOUT}";
elif command -v gtimeout &>/dev/null; then timeout_cmd="gtimeout ${PHASE_TIMEOUT}"; fi
${timeout_cmd} claude -p "/build-loop --max-cycles ${MAX_CYCLES}" \
  --print \
  --allowedTools "Bash,Read,Write,Edit,Glob,Grep,mcp__linear-server__*" \
  > "${OUTPUT_FILE}" 2>&1 || exit_code=$?

if [[ ${exit_code} -eq 124 ]]; then
  log "TIMEOUT: Build loop exceeded ${PHASE_TIMEOUT}s"
  echo "TIMEOUT" >> "${OUTPUT_FILE}"
  emit_friction "critical" "Build loop timed out after ${PHASE_TIMEOUT}s" "exit_code=124"
  WATCHDOG_PHASE="build_loop_timeout"; WATCHDOG_EXIT_CODE=124
elif [[ ${exit_code} -ne 0 ]]; then
  log "FAILED: Build loop exited with code ${exit_code}"
  emit_friction "high" "Build loop failed with exit code ${exit_code}" "exit_code=${exit_code}"
  WATCHDOG_PHASE="build_loop_execution"; WATCHDOG_EXIT_CODE=${exit_code}
else
  log "Build loop completed successfully"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

cat > "${RUN_DIR}/summary.txt" << EOF
Build Loop Run Summary
======================
Run ID:     ${RUN_ID}
Completed:  $(date -u +"%Y-%m-%dT%H:%M:%SZ")
Max Cycles: ${MAX_CYCLES}
Exit Code:  ${exit_code}
Dry Run:    ${DRY_RUN}
Delegation: ${ENABLE_DELEGATION}
Output:     ${OUTPUT_FILE}
EOF

log "Build loop run ${RUN_ID} complete (exit_code=${exit_code})"
log "Summary: ${RUN_DIR}/summary.txt"
log "Full log: ${LOG_DIR}/${RUN_ID}.log"

exit ${exit_code}
