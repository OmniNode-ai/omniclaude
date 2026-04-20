#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# headless-emit-wrapper.sh — Unified event emission for headless claude -p sessions.
#
# Source this at the start of any headless script to get emit_task_event().
# Events carry dispatch_surface: headless_claude and are sent to Kafka via
# kcat against $KAFKA_BOOTSTRAP_SERVERS (source ~/.omnibase/.env first).
#
# Fail-open: emission failures never crash the sourcing script.
# Repeated failures append to a local degraded-signal log so the problem
# is observable after the fact, and the first line of producer stderr is
# preserved alongside each EMIT_FAILED entry so the cause is debuggable.
#
# Usage:
#   source "$(dirname "$0")/headless-emit-wrapper.sh"
#   emit_task_event "task-assigned" "OMN-1234" '"session_id": "abc"'
#
# [OMN-7034] [OMN-9289 — migrate docker-exec rpk to host kcat]

# Guard against double-sourcing
if [[ -n "${_HEADLESS_EMIT_LOADED:-}" ]]; then
  return 0 2>/dev/null || true
fi
_HEADLESS_EMIT_LOADED=1

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

HEADLESS_EMIT_LOG="${HEADLESS_EMIT_LOG:-/tmp/headless-emit-degraded.log}"
HEADLESS_EMIT_TOPIC_PREFIX="onex.evt.omniclaude"
HEADLESS_EMIT_BROKERS="${KAFKA_BOOTSTRAP_SERVERS:-}"
HEADLESS_EMIT_KCAT_TIMEOUT_SEC="${HEADLESS_EMIT_KCAT_TIMEOUT_SEC:-5}"

# Counter for consecutive failures within this session
_HEADLESS_EMIT_FAIL_COUNT=0

# ---------------------------------------------------------------------------
# emit_task_event — Send a unified team event to Kafka
# ---------------------------------------------------------------------------
#
# Arguments:
#   $1  event_type   One of: task-assigned, task-progress, task-completed
#   $2  task_id      The task or ticket identifier (e.g. OMN-1234)
#   $3  extra_json   Optional additional JSON fields (without outer braces)
#                    e.g. '"session_id": "abc", "verdict": "PASS"'
#
# Returns 0 always (fail-open). Failures are logged to HEADLESS_EMIT_LOG
# with the kcat stderr tail so the root cause is preserved.

emit_task_event() {
  local event_type="${1:?emit_task_event requires event_type as \$1}"
  local task_id="${2:?emit_task_event requires task_id as \$2}"
  local extra_json="${3:-}"

  # Validate event_type
  case "${event_type}" in
    task-assigned|task-progress|task-completed) ;;
    *)
      echo "WARN[headless-emit]: unknown event_type '${event_type}', skipping" >&2
      return 0
      ;;
  esac

  local topic="${HEADLESS_EMIT_TOPIC_PREFIX}.${event_type}.v1"
  local timestamp
  timestamp="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

  # Build JSON payload
  local payload
  if [[ -n "${extra_json}" ]]; then
    payload="{\"task_id\": \"${task_id}\", \"dispatch_surface\": \"headless_claude\", \"agent_model\": \"claude-opus-4-6\", \"emitted_at\": \"${timestamp}\", \"run_id\": \"${ONEX_RUN_ID:-unknown}\", ${extra_json}}"
  else
    payload="{\"task_id\": \"${task_id}\", \"dispatch_surface\": \"headless_claude\", \"agent_model\": \"claude-opus-4-6\", \"emitted_at\": \"${timestamp}\", \"run_id\": \"${ONEX_RUN_ID:-unknown}\"}"
  fi

  local emit_err
  local rc=0

  if [[ -z "${HEADLESS_EMIT_BROKERS}" ]]; then
    emit_err="KAFKA_BOOTSTRAP_SERVERS unset (source ~/.omnibase/.env)"
    rc=1
  elif ! command -v kcat >/dev/null 2>&1; then
    emit_err="kcat not installed (brew install kcat)"
    rc=1
  else
    # Detect a timeout binary. macOS lacks `timeout` by default; Homebrew
    # coreutils ships it as `gtimeout`. Fall through to no-wrapper if
    # neither is present so emits still work on bare macOS.
    local timeout_cmd=""
    if command -v timeout >/dev/null 2>&1; then
      timeout_cmd="timeout"
    elif command -v gtimeout >/dev/null 2>&1; then
      timeout_cmd="gtimeout"
    fi

    # Produce via kcat against the configured broker. -P producer mode,
    # -c 1 exits after one message so kcat never blocks. Capture stderr
    # so the degraded log preserves the root cause.
    if [[ -n "${timeout_cmd}" ]]; then
      emit_err="$(printf '%s' "${payload}" \
        | "${timeout_cmd}" "${HEADLESS_EMIT_KCAT_TIMEOUT_SEC}" \
            kcat -P -b "${HEADLESS_EMIT_BROKERS}" -t "${topic}" -c 1 2>&1)"
    else
      emit_err="$(printf '%s' "${payload}" \
        | kcat -P -b "${HEADLESS_EMIT_BROKERS}" -t "${topic}" -c 1 2>&1)"
    fi
    rc=$?
  fi

  if [[ "${rc}" -eq 0 ]]; then
    _HEADLESS_EMIT_FAIL_COUNT=0
    return 0
  fi

  # Emission failed — record degraded signal with cause preserved.
  _HEADLESS_EMIT_FAIL_COUNT=$(( _HEADLESS_EMIT_FAIL_COUNT + 1 ))
  local err_tail
  err_tail="$(printf '%s' "${emit_err}" | tr '\n' ' ' | cut -c 1-240)"
  local fail_line
  fail_line="$(date -u +"%Y-%m-%dT%H:%M:%SZ") EMIT_FAILED count=${_HEADLESS_EMIT_FAIL_COUNT} topic=${topic} task_id=${task_id} rc=${rc} cause=${err_tail}"
  echo "${fail_line}" >> "${HEADLESS_EMIT_LOG}" 2>/dev/null || true
  echo "WARN[headless-emit]: ${fail_line}" >&2

  return 0  # fail-open
}
