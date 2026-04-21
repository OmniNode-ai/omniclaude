#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# canonical-clone-preflight.sh — git pull --ff-only preflight for cron tick wrappers
#
# Source this file then call: canonical_clone_preflight [log_prefix]
#
# Acquires an exclusive flock on /tmp/.omniclaude-auto-pull.lock (preventing
# concurrent pulls from multiple ticks or from interactive pull-all.sh runs),
# runs `git -C "$CANONICAL_CLONE" pull --ff-only`, logs the outcome, and
# returns non-zero on any failure. Never falls back to rebase or hard-reset.
#
# CANONICAL_CLONE defaults to ${OMNI_HOME:-$HOME/Code/omni_home}/omniclaude.
# Override by exporting CANONICAL_CLONE before sourcing.
#
# Log format (emitted via the caller's log() function if present, else echo):
#   preflight: pulled origin/main <before-sha> → <after-sha> (<N> commits)
#   preflight: already up-to-date (<sha>)
#   preflight: FAILED non-fast-forward — friction event written
#   preflight: FAILED <reason>
#
# On non-fast-forward the helper also writes a friction event JSON to
# $ONEX_STATE_DIR/friction/ so overnight monitoring can detect the divergence.
#
# [OMN-9405]

# ---------------------------------------------------------------------------
# Resolve canonical clone path
# ---------------------------------------------------------------------------

_preflight_canonical_clone() {
  if [[ -n "${CANONICAL_CLONE:-}" ]]; then
    echo "${CANONICAL_CLONE}"
    return
  fi
  local base="${OMNI_HOME:-${HOME}/Code/omni_home}"
  echo "${base}/omniclaude"
}

# ---------------------------------------------------------------------------
# Friction event writer (non-blocking, fail-open)
# ---------------------------------------------------------------------------

_preflight_write_friction() {
  local reason="$1"
  local clone_path="$2"
  local state_root="${ONEX_STATE_DIR:-${ONEX_REGISTRY_ROOT:-${HOME}/Code/omni_home}/.onex_state}"
  local friction_dir="${state_root}/friction"
  local ts
  ts="$(date -u +"%Y-%m-%dT%H-%M-%SZ")"
  local friction_file="${friction_dir}/preflight-non-ff-${ts}.json"

  mkdir -p "${friction_dir}" 2>/dev/null || true

  cat > "${friction_file}" 2>/dev/null << EOF || true
{
  "timestamp": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "skill": "canonical_clone_preflight",
  "surface": "cron_tick_preflight",
  "severity": "high",
  "description": "canonical-clone auto-pull failed: ${reason}",
  "clone_path": "${clone_path}",
  "ticket": "OMN-9405"
}
EOF
}

# ---------------------------------------------------------------------------
# Main preflight function — call from cron wrappers
# ---------------------------------------------------------------------------

canonical_clone_preflight() {
  local log_prefix="${1:-preflight}"
  local clone
  clone="$(_preflight_canonical_clone)"

  # Use caller's log() if defined, otherwise fall back to echo.
  _preflight_log() {
    if declare -f log >/dev/null 2>&1; then
      log "${log_prefix}: $1"
    else
      echo "[${log_prefix}] $1"
    fi
  }

  # Validate clone exists and is a git repo.
  if [[ ! -d "${clone}/.git" ]]; then
    _preflight_log "FAILED — canonical clone not found or not a git repo: ${clone}"
    return 1
  fi

  local lock_file="/tmp/.omniclaude-auto-pull.lock"
  local lock_fd=9

  # Open lock fd. If flock is unavailable (unlikely on macOS + Linux), skip
  # locking but log a warning rather than blocking the tick entirely.
  if ! command -v flock &>/dev/null; then
    _preflight_log "WARN — flock not available; skipping lock (install util-linux)"
  else
    # Open the lock file on fd 9, acquire exclusive non-blocking lock.
    # If another process holds it, exit 0 (skip — that tick is doing it).
    eval "exec ${lock_fd}>> \"${lock_file}\""
    if ! flock --nonblock "${lock_fd}" 2>/dev/null; then
      _preflight_log "lock held by another process — skipping pull (already in progress)"
      return 0
    fi
    # Lock fd released by the trap below. Single-quote the trap body so that
    # ${lock_fd} is expanded when the trap fires, not when the trap is set.
    # shellcheck disable=SC2064
    trap "exec ${lock_fd}>&-" RETURN
  fi

  # Capture sha before pull.
  local before_sha
  before_sha="$(git -C "${clone}" rev-parse --short HEAD 2>/dev/null || echo "unknown")"

  # Run the pull. Capture stderr for diagnosis.
  local pull_stderr
  pull_stderr="$(git -C "${clone}" pull --ff-only 2>&1)"
  local pull_exit=$?

  if [[ ${pull_exit} -ne 0 ]]; then
    # Distinguish non-ff from other failures (network, lock, etc.)
    if echo "${pull_stderr}" | grep -qi "not possible to fast-forward\|diverged\|cannot fast-forward"; then
      _preflight_log "FAILED non-fast-forward — friction event written"
      _preflight_log "git output: ${pull_stderr}"
      _preflight_write_friction "non-fast-forward: ${pull_stderr}" "${clone}"
    else
      _preflight_log "FAILED — git pull error: ${pull_stderr}"
      _preflight_write_friction "pull error: ${pull_stderr}" "${clone}"
    fi
    return 1
  fi

  local after_sha
  after_sha="$(git -C "${clone}" rev-parse --short HEAD 2>/dev/null || echo "unknown")"

  if [[ "${before_sha}" == "${after_sha}" ]]; then
    _preflight_log "already up-to-date (${after_sha})"
  else
    # Count commits advanced.
    local commit_count
    commit_count="$(git -C "${clone}" rev-list --count "${before_sha}..${after_sha}" 2>/dev/null || echo "?")"
    _preflight_log "pulled origin/main ${before_sha} → ${after_sha} (${commit_count} commits)"
  fi

  return 0
}
