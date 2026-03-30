#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# headless-emit-wrapper.sh — Unified event emission for headless claude -p sessions.
#
# Source this at the start of any headless script to get emit_task_event().
# Events carry dispatch_surface: headless_claude and are sent to Kafka
# via rpk (Redpanda CLI) inside the local Docker container.
#
# Fail-open: emission failures never crash the sourcing script.
# Repeated failures append to a local degraded-signal log so the problem
# is observable after the fact.
#
# Usage:
#   source "$(dirname "$0")/headless-emit-wrapper.sh"
#   emit_task_event "task-assigned" "OMN-1234" '"session_id": "abc"'
#
# [OMN-7034]

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
HEADLESS_EMIT_REDPANDA_CONTAINER="omnibase-infra-redpanda"

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
# Returns 0 always (fail-open). Failures are logged to HEADLESS_EMIT_LOG.

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

  # Attempt emission via rpk inside the Redpanda container
  if docker exec "${HEADLESS_EMIT_REDPANDA_CONTAINER}" \
    rpk topic produce "${topic}" --format '%v\n' 2>/dev/null <<< "${payload}"; then
    _HEADLESS_EMIT_FAIL_COUNT=0
    return 0
  fi

  # Emission failed — record degraded signal
  _HEADLESS_EMIT_FAIL_COUNT=$(( _HEADLESS_EMIT_FAIL_COUNT + 1 ))
  local fail_line
  fail_line="$(date -u +"%Y-%m-%dT%H:%M:%SZ") EMIT_FAILED count=${_HEADLESS_EMIT_FAIL_COUNT} topic=${topic} task_id=${task_id}"
  echo "${fail_line}" >> "${HEADLESS_EMIT_LOG}" 2>/dev/null || true
  echo "WARN[headless-emit]: ${fail_line}" >&2

  return 0  # fail-open
}
