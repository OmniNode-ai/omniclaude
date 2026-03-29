#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
# cron-closeout.sh — Headless close-out loop using claude -p (print mode)
#
# Each invocation reads pipeline state from a checkpoint file, executes one
# unit of work (a single autopilot close-out cycle), writes state back, and
# exits. A cron job or launchd agent calls this script on a fixed interval
# (e.g., every 30 minutes). Because each invocation is a fresh claude -p
# process, there is no context accumulation — solving the "prompt is too long"
# problem that kills CronCreate-based autopilot after the first pass.
#
# Usage:
#   cron-closeout.sh                    # Default: 30-minute interval docs
#   cron-closeout.sh --dry-run          # Log decisions without side effects
#   cron-closeout.sh --max-passes 5     # Cap total passes (default: unlimited)
#   cron-closeout.sh --checkpoint-dir <path>  # Custom checkpoint directory
#
# Requirements:
#   - claude CLI installed and on PATH
#   - ANTHROPIC_API_KEY set
#   - GITHUB_TOKEN set (for PR operations)
#   - LINEAR_API_KEY set (for ticket updates)
#
# Checkpoint file: $CHECKPOINT_DIR/cron-closeout-state.yaml
# Lock file:       $CHECKPOINT_DIR/cron-closeout.lock
#
# [OMN-6887]

set -euo pipefail

# --- Configuration ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OMNI_HOME="${OMNI_HOME:?OMNI_HOME must be set}"  # local-path-ok: env var with no default
DEFAULT_CHECKPOINT_DIR="${OMNI_HOME}/.onex_state/pipeline_checkpoints"
LOCK_TIMEOUT_SECONDS=2700  # 45 minutes — matches autopilot cycle mutex

# --- Argument parsing ---
DRY_RUN=false
MAX_PASSES=0  # 0 = unlimited
CHECKPOINT_DIR="$DEFAULT_CHECKPOINT_DIR"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --max-passes)
      MAX_PASSES="$2"
      shift 2
      ;;
    --checkpoint-dir)
      CHECKPOINT_DIR="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

# --- Ensure checkpoint directory exists ---
mkdir -p "$CHECKPOINT_DIR"

CHECKPOINT_FILE="$CHECKPOINT_DIR/cron-closeout-state.yaml"
LOCK_FILE="$CHECKPOINT_DIR/cron-closeout.lock"
LOG_DIR="${OMNI_HOME}/.onex_state/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/cron-closeout-$(date +%Y%m%d).log"

# --- Logging ---
log() {
  local ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "[$ts] $*" | tee -a "$LOG_FILE"
}

# --- Lock management ---
acquire_lock() {
  if [[ -f "$LOCK_FILE" ]]; then
    local lock_time
    lock_time="$(stat -f %m "$LOCK_FILE" 2>/dev/null || stat -c %Y "$LOCK_FILE" 2>/dev/null)"
    local now
    now="$(date +%s)"
    local age=$(( now - lock_time ))

    if [[ $age -lt $LOCK_TIMEOUT_SECONDS ]]; then
      log "SKIP: Previous invocation still running (lock age: ${age}s < ${LOCK_TIMEOUT_SECONDS}s)"
      exit 0
    else
      log "WARN: Stale lock detected (age: ${age}s). Removing."
      rm -f "$LOCK_FILE"
    fi
  fi

  echo "pid=$$" > "$LOCK_FILE"
  echo "started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOCK_FILE"
  trap 'rm -f "$LOCK_FILE"' EXIT
}

release_lock() {
  rm -f "$LOCK_FILE"
}

# --- Checkpoint read/write ---
read_checkpoint() {
  if [[ -f "$CHECKPOINT_FILE" ]]; then
    # Extract fields from YAML (simple grep-based for portability)
    PASS_COUNT=$(grep '^pass_count:' "$CHECKPOINT_FILE" | awk '{print $2}' || echo "0")
    LAST_STATUS=$(grep '^last_status:' "$CHECKPOINT_FILE" | awk '{print $2}' || echo "none")
    LAST_RUN=$(grep '^last_run_at:' "$CHECKPOINT_FILE" | awk '{print $2}' || echo "never")
    CONSECUTIVE_FAILURES=$(grep '^consecutive_failures:' "$CHECKPOINT_FILE" | awk '{print $2}' || echo "0")
  else
    PASS_COUNT=0
    LAST_STATUS="none"
    LAST_RUN="never"
    CONSECUTIVE_FAILURES=0
  fi
}

write_checkpoint() {
  local status="$1"
  local new_pass_count=$(( PASS_COUNT + 1 ))
  local new_failures

  if [[ "$status" == "success" || "$status" == "noop" ]]; then
    new_failures=0
  else
    new_failures=$(( CONSECUTIVE_FAILURES + 1 ))
  fi

  cat > "$CHECKPOINT_FILE" <<YAML
# cron-closeout checkpoint — written by cron-closeout.sh [OMN-6887]
# Do not edit manually.
schema_version: "1.0.0"
pass_count: $new_pass_count
last_status: $status
last_run_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)
consecutive_failures: $new_failures
dry_run: $DRY_RUN
YAML

  log "Checkpoint written: pass=$new_pass_count status=$status failures=$new_failures"
}

# --- Pre-flight checks ---
preflight() {
  if ! command -v claude &>/dev/null; then
    log "ERROR: claude CLI not found on PATH"
    exit 1
  fi

  if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
    log "ERROR: ANTHROPIC_API_KEY not set"
    exit 1
  fi

  if [[ -z "${GITHUB_TOKEN:-}" ]]; then
    log "WARN: GITHUB_TOKEN not set — PR operations will fail"
  fi
}

# --- Main execution ---
main() {
  log "=== cron-closeout invocation starting ==="
  preflight
  acquire_lock
  read_checkpoint

  # Check pass cap
  if [[ $MAX_PASSES -gt 0 && $PASS_COUNT -ge $MAX_PASSES ]]; then
    log "SKIP: Max passes reached ($PASS_COUNT >= $MAX_PASSES)"
    release_lock
    exit 0
  fi

  # Check consecutive failure circuit breaker
  if [[ $CONSECUTIVE_FAILURES -ge 3 ]]; then
    log "HALT: 3 consecutive failures detected. Manual intervention required."
    log "  Last status: $LAST_STATUS"
    log "  Last run: $LAST_RUN"
    log "  Reset by deleting or editing: $CHECKPOINT_FILE"
    release_lock
    exit 1
  fi

  log "Starting pass $(( PASS_COUNT + 1 )) (last: $LAST_STATUS at $LAST_RUN)"

  # Build the claude -p prompt
  local dry_run_flag=""
  if [[ "$DRY_RUN" == "true" ]]; then
    dry_run_flag="Use --dry-run mode: log all decisions but do not commit, push, or merge."
  fi

  local prompt
  prompt="Run the autopilot skill in close-out mode. Execute one full close-out cycle.

Context:
- This is pass $(( PASS_COUNT + 1 )) of the cron-based close-out loop.
- Previous status: $LAST_STATUS
- Previous run: $LAST_RUN
- Consecutive failures: $CONSECUTIVE_FAILURES
$dry_run_flag

Execute: /autopilot --mode close-out --autonomous

After completion, report the cycle outcome as one of: success, noop, failure, halt."

  # Tool allowlist — minimal surface for close-out operations
  local allowed_tools="Bash,Read,Write,Edit,Glob,Grep"
  allowed_tools+=",mcp__linear-server__get_issue"
  allowed_tools+=",mcp__linear-server__save_issue"
  allowed_tools+=",mcp__linear-server__list_issues"
  allowed_tools+=",mcp__linear-server__save_comment"

  # Execute claude -p with fresh context
  local exit_code=0
  local output_file="$LOG_DIR/cron-closeout-pass-$(( PASS_COUNT + 1 ))-$(date +%H%M%S).log"

  log "Invoking claude -p (output: $output_file)"

  if claude -p "$prompt" \
    --allowedTools "$allowed_tools" \
    > "$output_file" 2>&1; then
    log "claude -p completed successfully"

    # Parse outcome from output (last line containing success/noop/failure/halt)
    local outcome
    outcome=$(grep -oiE '(success|noop|failure|halt)' "$output_file" | tail -1 || echo "unknown")
    outcome=$(echo "$outcome" | tr '[:upper:]' '[:lower:]')

    case "$outcome" in
      success|noop)
        write_checkpoint "$outcome"
        log "Pass completed: $outcome"
        ;;
      failure|halt)
        write_checkpoint "$outcome"
        log "Pass completed with issues: $outcome"
        ;;
      *)
        write_checkpoint "unknown"
        log "WARN: Could not parse outcome from claude output. Recorded as unknown."
        ;;
    esac
  else
    exit_code=$?
    log "ERROR: claude -p exited with code $exit_code"
    write_checkpoint "failure"
  fi

  release_lock
  log "=== cron-closeout invocation complete ==="
  exit ${exit_code}
}

main "$@"
