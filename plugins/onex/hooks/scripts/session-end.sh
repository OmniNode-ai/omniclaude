#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# SessionEnd Hook - Portable Plugin Version
# Captures session completion and aggregate statistics
# Also logs active ticket for audit/observability (OMN-1830)
# Performance target: <50ms execution time
# NOTE: This hook is audit-only - NO context injection, NO contract mutation

set -euo pipefail

# Portable Plugin Configuration
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
HOOKS_DIR="${PLUGIN_ROOT}/hooks"
HOOKS_LIB="${HOOKS_DIR}/lib"
LOG_FILE="${HOOKS_DIR}/logs/hook-session-end.log"

# Detect project root
PROJECT_ROOT="${PLUGIN_ROOT}/../.."
if [[ -f "${PROJECT_ROOT}/.env" ]]; then
    PROJECT_ROOT="$(cd "${PROJECT_ROOT}" && pwd)"
elif [[ -n "${CLAUDE_PROJECT_DIR:-}" ]]; then
    PROJECT_ROOT="${CLAUDE_PROJECT_DIR}"
else
    PROJECT_ROOT="$(pwd)"
fi

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_FILE")"

export PYTHONPATH="${PROJECT_ROOT}:${PLUGIN_ROOT}/lib:${HOOKS_LIB}:${PYTHONPATH:-}"

# Load environment variables (before common.sh so KAFKA_BOOTSTRAP_SERVERS is available)
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    set -a
    source "$PROJECT_ROOT/.env" 2>/dev/null || true
    set +a
fi

# Source shared functions (provides PYTHON_CMD, KAFKA_ENABLED, get_time_ms, log)
source "${HOOKS_DIR}/scripts/common.sh"

# Read stdin (validate JSON; fall back to empty object on malformed input)
INPUT=$(cat)
if ! echo "$INPUT" | jq -e . >/dev/null 2>>"$LOG_FILE"; then
    log "ERROR: Malformed JSON on stdin, using empty object"
    INPUT='{}'
fi

log "SessionEnd hook triggered (plugin mode)"

# Extract session metadata
SESSION_ID=$(echo "$INPUT" | jq -r '.sessionId // ""' 2>/dev/null || echo "")
SESSION_DURATION=$(echo "$INPUT" | jq -r '.durationMs // 0' 2>/dev/null || echo "0")
SESSION_REASON=$(echo "$INPUT" | jq -r '.reason // "other"' 2>/dev/null || echo "other")

# Extract tool call count from session payload (if available)
TOOL_CALLS_COMPLETED=$(echo "$INPUT" | jq -r '.tools_used_count // 0' 2>/dev/null || echo "0")
if [[ "$TOOL_CALLS_COMPLETED" == "0" ]]; then
    log "Phase 1: tools_used_count absent or zero — SUCCESS gate unreachable (see OMN-1892); raw outcome still emitted via OMN-2356"
fi

# Validate reason is one of the allowed values
case "$SESSION_REASON" in
    clear|logout|prompt_input_exit|other) ;;
    *) SESSION_REASON="other" ;;
esac

if [[ -n "$SESSION_ID" ]]; then
    log "Session ID: $SESSION_ID"
fi
log "Duration: ${SESSION_DURATION}ms"
log "Reason: $SESSION_REASON"

# -----------------------------
# Active Ticket Detection (OMN-1830)
# -----------------------------
# Check for active ticket (for audit logging only - NO context injection, NO mutation)
TICKET_INJECTION_ENABLED="${OMNICLAUDE_TICKET_INJECTION_ENABLED:-true}"
TICKET_INJECTION_ENABLED=$(_normalize_bool "$TICKET_INJECTION_ENABLED")
ACTIVE_TICKET=""

if [[ "${TICKET_INJECTION_ENABLED}" == "true" ]] && [[ -f "${HOOKS_LIB}/ticket_context_injector.py" ]]; then
    # Use CLI interface for consistency with session-start.sh (OMN-1830)
    TICKET_OUTPUT=$(echo '{}' | "$PYTHON_CMD" "${HOOKS_LIB}/ticket_context_injector.py" 2>>"$LOG_FILE") || TICKET_OUTPUT='{}'
    ACTIVE_TICKET=$(echo "$TICKET_OUTPUT" | jq -r '.ticket_id // empty' 2>/dev/null) || ACTIVE_TICKET=""

    if [[ -n "$ACTIVE_TICKET" ]]; then
        log "Session ended with active ticket: $ACTIVE_TICKET"
    else
        log "Session ended with no active ticket"
    fi
elif [[ "${TICKET_INJECTION_ENABLED}" != "true" ]]; then
    log "Active ticket detection disabled (TICKET_INJECTION_ENABLED=false)"
else
    log "Ticket context injector not found, skipping active ticket detection"
fi

# Call session intelligence module (async, non-blocking)
(
    $PYTHON_CMD "${HOOKS_LIB}/session_intelligence.py" \
        --mode end \
        --session-id "${SESSION_ID}" \
        --metadata "{\"hook_duration_ms\": ${SESSION_DURATION}}" \
        >> "$LOG_FILE" 2>&1 || { rc=$?; log "Session end logging failed (exit=$rc)"; }
) &

# Convert duration from ms to seconds once (used by all subshells below)
# Uses awk instead of Python to avoid ~30-50ms interpreter startup cost
# on the synchronous path (preserves <50ms SessionEnd budget).
DURATION_SECONDS="0"
if [[ -n "$SESSION_DURATION" && "$SESSION_DURATION" != "0" ]]; then
    # Sanitize: accept integer or float durationMs from Claude Code.
    # Float values (e.g. 45200.5) are valid — truncate to integer to satisfy
    # the schema's duration_ms: int declaration and pass them to awk.
    if [[ "$SESSION_DURATION" =~ ^[0-9]+$ ]]; then
        : # Already a strict integer — no change needed
    elif [[ "$SESSION_DURATION" =~ ^[0-9]+\.[0-9]+$ ]]; then
        # Float: truncate fractional part (e.g. 45200.5 → 45200)
        _raw_duration="$SESSION_DURATION"
        SESSION_DURATION="${SESSION_DURATION%%.*}"
        log "WARNING: durationMs is a float (${_raw_duration}), truncating to integer (${SESSION_DURATION})"
    else
        log "WARNING: durationMs has unexpected format '${SESSION_DURATION}', resetting to 0"
        SESSION_DURATION=0
    fi
    DURATION_SECONDS=$(awk -v ms="$SESSION_DURATION" 'BEGIN{v=ms/1000; printf "%.3f", (v<0?0:v)}' 2>/dev/null || echo "0")
fi

# Read correlation_id from state file BEFORE backgrounded subshells (OMN-2190)
# Must happen in main shell to avoid race with cleanup at end.
# Uses jq instead of Python to avoid ~30-50ms interpreter startup on the
# synchronous path (preserves <50ms SessionEnd budget).
CORRELATION_ID=""
CORRELATION_STATE_FILE="${HOME}/.claude/hooks/.state/correlation_id.json"
if [[ -f "$CORRELATION_STATE_FILE" ]]; then
    CORRELATION_ID=$(jq -r '.correlation_id // empty' "$CORRELATION_STATE_FILE" 2>/dev/null) || CORRELATION_ID=""
fi

# Emit session.ended event to Kafka (backgrounded for parallelism)
# Uses emit_client_wrapper with daemon fan-out (OMN-1632)
# PIDs tracked for drain-then-stop at end (no fixed sleep needed at SessionEnd).
EMIT_PIDS=()
if [[ "$KAFKA_ENABLED" == "true" ]]; then
    (
        # Build JSON payload for emit daemon (includes active_ticket for OMN-1830)
        # DURATION_SECONDS pre-computed in main shell; map "0" to null (no duration info)
        SESSION_PAYLOAD=$(jq -n \
            --arg session_id "$SESSION_ID" \
            --arg reason "$SESSION_REASON" \
            --arg duration_seconds "$DURATION_SECONDS" \
            --arg active_ticket "$ACTIVE_TICKET" \
            '{
                session_id: $session_id,
                reason: $reason,
                duration_seconds: (if $duration_seconds == "0" then null else ($duration_seconds | tonumber) end),
                active_ticket: (if $active_ticket == "" then null else $active_ticket end)
            }' 2>/dev/null)

        # Validate payload was constructed successfully
        if [[ -z "$SESSION_PAYLOAD" || "$SESSION_PAYLOAD" == "null" ]]; then
            log "WARNING: Failed to construct session payload (jq failed), skipping emission"
        else
            emit_via_daemon "session.ended" "$SESSION_PAYLOAD" 100
        fi
    ) &
    EMIT_PIDS+=($!)

    # Session outcome derivation + emission + feedback guardrails (OMN-1735, OMN-1892)
    # Consolidated into a single backgrounded subshell so the DERIVED_OUTCOME
    # Python computation (~30-50ms interpreter startup) stays off the sync path.
    (
        # Define accumulator path up front so the trap below can reference it
        # regardless of which exit path is taken.
        SESSION_STATE_FILE="/tmp/omniclaude-session-${SESSION_ID}.json"  # noqa: S108  # nosec B108

        # Validate SESSION_ID once for all outcome/feedback work
        if [[ -z "$SESSION_ID" ]]; then
            log "WARNING: SESSION_ID is empty, skipping session.outcome and feedback"
            exit 0
        fi

        # Ensure accumulator is always cleaned up — including early-exit paths.
        # Registered AFTER the empty-SESSION_ID guard so SESSION_STATE_FILE has a
        # proper session-specific path (not /tmp/omniclaude-session-.json, which could
        # collide between concurrent sessions with empty IDs).
        # NOTE: the trap DOES fire on UUID-format-invalid exit (line 191-194) — this is
        # intentional; a file written under a non-UUID session ID is still cleaned up.
        # The trap also fires on the normal completion path (after the file is read).
        trap 'rm -f "$SESSION_STATE_FILE"' EXIT

        # Validate UUID format (8-4-4-4-12 structure, case-insensitive)
        if [[ ! "$SESSION_ID" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]]; then
            log "WARNING: SESSION_ID '$SESSION_ID' is not valid UUID format, skipping session.outcome and feedback"
            exit 0
        fi

        # ===================================================================
        # PHASE 1 PLUMBING (OMN-1892): Outcome derivation inputs are
        # partially hardcoded. Current state:
        #   - exit_code=0: Always 0 (hooks must never exit non-zero per CLAUDE.md)
        #   - session_output: Uses session reason (clear/logout/prompt_input_exit/
        #     other), NOT captured stdout. Outcome will not resolve to FAILED
        #     until session_output carries error markers (Error:, Exception:, etc.)
        #   - tool_calls_completed: Extracted from tools_used_count (best-effort);
        #     may still be 0 if field is absent from SessionEnd payload.
        #     SUCCESS requires tool_calls > 0 AND completion markers.
        # Unreachable gates: SUCCESS (no completion markers in reason codes),
        #   FAILED (exit_code always 0, no error markers in reason codes).
        # Result: Outcome currently resolves to abandoned or unknown only.
        # Future tickets:
        #   - tool_calls_completed: Wire from session aggregation service
        #   - session_output: Wire from captured session output/stdout
        # ===================================================================
        # Derive session outcome (pure Python, no I/O)
        # Python startup is ~30-50ms but runs in this backgrounded subshell,
        # not on the sync path. Falls back to "unknown" on failure.
        DERIVED_OUTCOME=$(HOOKS_LIB="$HOOKS_LIB" SESSION_REASON="$SESSION_REASON" DURATION_SECONDS="$DURATION_SECONDS" TOOL_CALLS_COMPLETED="$TOOL_CALLS_COMPLETED" \
            "$PYTHON_CMD" -c "
import os, sys
sys.path.insert(0, os.environ['HOOKS_LIB'])
from session_outcome import derive_session_outcome
session_reason = os.environ.get('SESSION_REASON', 'other')
duration_str = os.environ.get('DURATION_SECONDS', '0') or '0'
tool_calls_str = os.environ.get('TOOL_CALLS_COMPLETED', '0') or '0'
if not tool_calls_str.isdigit():
    print(f'WARNING: TOOL_CALLS_COMPLETED={tool_calls_str!r} not numeric, using 0', file=sys.stderr)
try:
    duration = float(duration_str)
    if duration < 0:
        print(f'WARNING: DURATION_SECONDS={duration} is negative, using 0', file=sys.stderr)
        duration = 0.0
except ValueError:
    print(f'WARNING: DURATION_SECONDS={duration_str!r} not numeric, using 0', file=sys.stderr)
    duration = 0.0
result = derive_session_outcome(
    exit_code=0,
    session_output=session_reason,
    tool_calls_completed=int(tool_calls_str) if tool_calls_str.isdigit() else 0,
    duration_seconds=duration,
)
print(result.outcome)
" 2>>"$LOG_FILE") || DERIVED_OUTCOME="unknown"

        log "Session outcome derived: ${DERIVED_OUTCOME}"
        if [[ "$DERIVED_OUTCOME" == "unknown" || "$DERIVED_OUTCOME" == "abandoned" ]]; then
            log "Phase 1: outcome=$DERIVED_OUTCOME (SUCCESS/FAILED gates require wired session_output and tool_calls; see OMN-1892)"
        fi

        # --- Emit session.outcome event ---
        # Wire payload must match ModelClaudeCodeSessionOutcome (extra="forbid"):
        #   session_id, outcome, correlation_id
        # Stripped: emitted_at, active_ticket (OMN-2190)

        if ! OUTCOME_PAYLOAD=$(jq -n \
            --arg session_id "$SESSION_ID" \
            --arg outcome "$DERIVED_OUTCOME" \
            --arg correlation_id "$CORRELATION_ID" \
            '{
                session_id: $session_id,
                outcome: $outcome,
                correlation_id: (if $correlation_id == "" then null else $correlation_id end)
            }' 2>>"$LOG_FILE"); then
            log "WARNING: Failed to construct outcome payload (jq failed), skipping emission"
        elif [[ -z "$OUTCOME_PAYLOAD" || "$OUTCOME_PAYLOAD" == "null" ]]; then
            log "WARNING: outcome payload empty or null, skipping emission"
        else
            emit_via_daemon "session.outcome" "$OUTCOME_PAYLOAD" 100
        fi

        # --- Emit routing.outcome.raw event (OMN-2356) ---
        # Replaces the no-op feedback guardrail loop that used hardcoded/zero values.
        # Emits RAW OBSERVABLE FACTS only — no derived scores.
        # utilization_score and agent_match_score are computed by omniintelligence's
        # routing-feedback consumer using its own context (Invariant 5 compliance).
        #
        # Data sources:
        #   injection_occurred / patterns_injected_count / agent_selected /
        #   routing_confidence: read from session accumulator written by
        #   user-prompt-submit.sh at /tmp/omniclaude-session-${SESSION_ID}.json
        #
        #   tool_calls_count: tools_used_count from Claude SessionEnd payload
        #   duration_ms: durationMs from Claude SessionEnd payload

        RAW_INJECTION_OCCURRED="false"
        RAW_PATTERNS_COUNT=0
        RAW_AGENT_SELECTED=""
        RAW_ROUTING_CONFIDENCE=0.0

        if [[ -f "$SESSION_STATE_FILE" ]]; then
            RAW_INJECTION_OCCURRED=$(jq -r '.injection_occurred // false' "$SESSION_STATE_FILE" 2>>"$LOG_FILE") || RAW_INJECTION_OCCURRED="false"
            RAW_PATTERNS_COUNT=$(jq -r '.patterns_injected_count // 0' "$SESSION_STATE_FILE" 2>>"$LOG_FILE") || RAW_PATTERNS_COUNT=0
            RAW_AGENT_SELECTED=$(jq -r '.agent_selected // ""' "$SESSION_STATE_FILE" 2>>"$LOG_FILE") || RAW_AGENT_SELECTED=""
            RAW_ROUTING_CONFIDENCE=$(jq -r '.routing_confidence // 0.0' "$SESSION_STATE_FILE" 2>>"$LOG_FILE") || RAW_ROUTING_CONFIDENCE=0.0
            log "Session accumulator read: injection=$RAW_INJECTION_OCCURRED patterns=$RAW_PATTERNS_COUNT agent=${RAW_AGENT_SELECTED:-none}"
        else
            log "Session accumulator not found (${SESSION_STATE_FILE}) — no UserPromptSubmit this session"
        fi

        # Sanitize: ensure numeric fields are numeric
        [[ "$RAW_PATTERNS_COUNT" =~ ^[0-9]+$ ]] || RAW_PATTERNS_COUNT=0
        [[ "$RAW_ROUTING_CONFIDENCE" =~ ^[0-9]+(\.[0-9]+)?$ ]] || RAW_ROUTING_CONFIDENCE=0.0
        # Slash-command sentinel: agent_selected="" + confidence=1.0 means routing was
        # bypassed (not a real routing decision). Zero out confidence so omniintelligence
        # consumers receive an unambiguous no-routing-decision signal (confidence=0.0,
        # agent_selected="") instead of a misleading high-confidence empty-agent pair.
        # Use awk for numeric comparison: jq may emit integer 1 instead of float 1.0
        # when the value is an exact integer, causing string equality "== 1.0" to miss it.
        if [[ -z "$RAW_AGENT_SELECTED" ]] && [[ -n "$RAW_ROUTING_CONFIDENCE" ]] && awk "BEGIN{exit !($RAW_ROUTING_CONFIDENCE + 0 == 1)}"; then
            log "Slash-command sentinel detected (agent_selected='', confidence=1.0) — zeroing routing_confidence"
            RAW_ROUTING_CONFIDENCE="0.0"
        fi
        # Clamp to [0.0, 1.0] — le=1.0 constraint matches schema
        awk "BEGIN{exit !($RAW_ROUTING_CONFIDENCE > 1.0)}" 2>/dev/null && RAW_ROUTING_CONFIDENCE="1.0"
        # Three-branch float-handling for TOOL_CALLS_COMPLETED (mirrors SESSION_DURATION logic).
        # Float values (e.g. 5.0) are valid — strip fractional part and warn; anything else resets to 0.
        # NOTE: derive_session_outcome (line 216) already consumed TOOL_CALLS_COMPLETED before this
        # sanitization block. It handles the float case via its own isdigit() guard (falls back to 0
        # with a warning). The sanitized value here is used exclusively for the raw outcome payload.
        if [[ "$TOOL_CALLS_COMPLETED" =~ ^[0-9]+$ ]]; then
            : # Already a strict integer — no change needed
        elif [[ "$TOOL_CALLS_COMPLETED" =~ ^[0-9]+\.[0-9]+$ ]]; then
            _raw_tool_calls="$TOOL_CALLS_COMPLETED"
            TOOL_CALLS_COMPLETED="${TOOL_CALLS_COMPLETED%%.*}"
            log "WARNING: tools_used_count is a float (${_raw_tool_calls}), truncating to integer (${TOOL_CALLS_COMPLETED})"
        else
            log "WARNING: tools_used_count has unexpected format '${TOOL_CALLS_COMPLETED}', resetting to 0"
            TOOL_CALLS_COMPLETED=0
        fi
        if [[ "$RAW_INJECTION_OCCURRED" == "null" ]]; then
            log "WARNING: injection_occurred is null in accumulator — resetting to false"
            RAW_INJECTION_OCCURRED="false"
        fi
        [[ "$RAW_INJECTION_OCCURRED" == "true" ]] || RAW_INJECTION_OCCURRED="false"

        # Use Python for a portable ISO timestamp with millisecond precision.
        # `date -u +"%Y-%m-%dT%H:%M:%S.%3NZ"` exits 0 on macOS but produces a
        # literal ".3NZ" suffix instead of milliseconds, causing fromisoformat()
        # validation to fail downstream. Fall back to second-precision if Python
        # is unavailable (unlikely — PYTHON_CMD is required by this hook).
        RAW_EMITTED_AT=$("$PYTHON_CMD" -c 'from datetime import datetime, timezone; print(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z")' 2>/dev/null \
            || date -u +"%Y-%m-%dT%H:%M:%SZ")
        # SESSION_DURATION is pre-sanitized to integer in the outer shell (lines 109-126)
        # before this subshell forks — no re-check needed here.
        if ! RAW_OUTCOME_PAYLOAD=$(jq -n \
            --arg session_id "$SESSION_ID" \
            --argjson injection_occurred "$RAW_INJECTION_OCCURRED" \
            --argjson patterns_injected_count "$RAW_PATTERNS_COUNT" \
            --argjson tool_calls_count "$TOOL_CALLS_COMPLETED" \
            --argjson duration_ms "$SESSION_DURATION" \
            --arg agent_selected "$RAW_AGENT_SELECTED" \
            --argjson routing_confidence "$RAW_ROUTING_CONFIDENCE" \
            --arg emitted_at "$RAW_EMITTED_AT" \
            '{
                session_id: $session_id,
                injection_occurred: $injection_occurred,
                patterns_injected_count: $patterns_injected_count,
                tool_calls_count: $tool_calls_count,
                duration_ms: $duration_ms,
                agent_selected: $agent_selected,
                routing_confidence: $routing_confidence,
                emitted_at: $emitted_at
            }' 2>>"$LOG_FILE"); then
            log "WARNING: Failed to construct routing.outcome.raw payload (jq failed), skipping emission"
        elif [[ -z "$RAW_OUTCOME_PAYLOAD" || "$RAW_OUTCOME_PAYLOAD" == "null" ]]; then
            log "WARNING: routing.outcome.raw payload empty or null, skipping emission"
        else
            emit_via_daemon "routing.outcome.raw" "$RAW_OUTCOME_PAYLOAD" 100
            log "routing.outcome.raw emitted: injection=$RAW_INJECTION_OCCURRED patterns=$RAW_PATTERNS_COUNT tool_calls=$TOOL_CALLS_COMPLETED"
        fi

    ) &
    EMIT_PIDS+=($!)

    log "Session event emission started via emit daemon"
else
    log "Kafka emission skipped (KAFKA_ENABLED=$KAFKA_ENABLED)"
fi

# Clean up correlation state
if [[ -f "${HOOKS_LIB}/correlation_manager.py" ]]; then
    HOOKS_LIB="$HOOKS_LIB" $PYTHON_CMD -c "
import os, sys
sys.path.insert(0, os.environ['HOOKS_LIB'])
from correlation_manager import get_registry
get_registry().clear()
" 2>/dev/null || true
fi

# -----------------------------
# Clear session injection marker (OMN-1675)
# -----------------------------
if [[ -f "${HOOKS_LIB}/session_marker.py" ]] && [[ -n "${SESSION_ID}" ]]; then
    $PYTHON_CMD "${HOOKS_LIB}/session_marker.py" clear --session-id "${SESSION_ID}" 2>>"$LOG_FILE" || true
    log "Cleared session injection marker"
fi

# -----------------------------
# Session State Teardown (OMN-2119)
# -----------------------------
# Transition the active run to run_ended via cmd_end.
# Mirrors the cmd_init call in session-start.sh. Reads active_run_id from
# the session index (session.json), then pipes it to the adapter's "end"
# command. Runs in background to stay within the <50ms budget.
# If no active run exists (e.g., init failed), this is a no-op.
if [[ -f "${HOOKS_LIB}/node_session_state_adapter.py" ]]; then
    (
        # Read active_run_id from session index
        SESSION_STATE_DIR="${CLAUDE_STATE_DIR:-${HOME}/.claude/state}"
        SESSION_INDEX="${SESSION_STATE_DIR}/session.json"
        ACTIVE_RUN_ID=""
        if [[ -f "$SESSION_INDEX" ]]; then
            ACTIVE_RUN_ID=$(jq -r '.active_run_id // ""' "$SESSION_INDEX" 2>/dev/null) || ACTIVE_RUN_ID=""
        fi

        if [[ -n "$ACTIVE_RUN_ID" ]] && [[ "$ACTIVE_RUN_ID" != "null" ]]; then
            adapter_stdout=$(echo "{\"run_id\": \"${ACTIVE_RUN_ID}\"}" | "$PYTHON_CMD" "${HOOKS_LIB}/node_session_state_adapter.py" end 2>>"$LOG_FILE")
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] [session-state] cmd_end stdout: ${adapter_stdout:-<empty>}" >> "$LOG_FILE"
        else
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] [session-state] No active run to end (active_run_id empty or absent)" >> "$LOG_FILE"
        fi
    ) &
    log "Session state teardown started in background (PID: $!)"
fi

# Output response immediately so Claude Code can proceed with shutdown.
# Worktree cleanup (below) is backgrounded to preserve <50ms SessionEnd budget.
echo "$INPUT"

# -----------------------------
# Worktree Cleanup (OMN-1856)
# -----------------------------
# Clean up agent-created worktrees from this session.
# Only targets ~/.claude/worktrees/ with valid .claude-session.json markers.
# Uses git worktree remove (never rm -rf). Idempotent.
#
# Runs in a backgrounded subshell so find/jq/git subprocess invocations
# do not block Claude Code (performance budget: <50ms sync path).

WORKTREE_BASE="${HOME}/.claude/worktrees"

if [[ -d "$WORKTREE_BASE" ]]; then
    (
    # Guard: refuse to run cleanup without a session ID — an empty SESSION_ID
    # would match markers whose session_id field is also empty/missing, leading
    # to unintended removal of worktrees belonging to other sessions.
    if [[ -z "$SESSION_ID" ]]; then
        log "WORKTREE: No session ID — skipping worktree cleanup"
        exit 0
    fi

    # Canonicalize WORKTREE_BASE to its physical path so symlink-based
    # path traversal cannot bypass the case-prefix guard below.
    WORKTREE_BASE=$(cd "$WORKTREE_BASE" 2>/dev/null && pwd -P) || {
        log "WARNING: Cannot canonicalize WORKTREE_BASE, skipping worktree cleanup"
        exit 0
    }

    _wt_candidates=0
    _wt_removed=0
    _wt_skipped=0

    # Scan for markers under ~/.claude/worktrees/{repo}/{branch}/.
    # Use -mindepth 2 (at least {repo}/{file}) and -maxdepth 10 to handle
    # branch names containing slashes (e.g., "feature/auth",
    # "jonahgabriel/omn-1856") — git creates nested subdirectories for
    # each path component, so the marker can appear at depth 4+.
    # Safety scoping is provided by the path-prefix guard, session-id
    # matching, and git-state checks below.
    while IFS= read -r -d '' _wt_marker; do
        _wt_dir="$(dirname "$_wt_marker")"
        _wt_candidates=$((_wt_candidates + 1))

        # G1: Read and validate marker
        if ! _wt_data=$(jq -e '.' "$_wt_marker" 2>/dev/null); then
            log "STALE: ${_wt_dir} - malformed .claude-session.json"
            _wt_skipped=$((_wt_skipped + 1))
            continue
        fi

        _wt_marker_session=$(echo "$_wt_data" | jq -r '.session_id // empty' 2>/dev/null)
        _wt_parent_repo=$(echo "$_wt_data" | jq -r '.parent_repo_path // empty' 2>/dev/null)
        _wt_cleanup_policy=$(echo "$_wt_data" | jq -r '.cleanup_policy // empty' 2>/dev/null)

        # G1b: cleanup_policy must be "session-end" (per SKILL.md contract)
        if [[ "$_wt_cleanup_policy" != "session-end" ]]; then
            log "WORKTREE: SKIP ${_wt_dir} — cleanup_policy is '${_wt_cleanup_policy}', not session-end"
            _wt_skipped=$((_wt_skipped + 1))
            continue
        fi

        # G2: Session ID must match current session
        if [[ "$_wt_marker_session" != "$SESSION_ID" ]]; then
            log "SKIP: ${_wt_dir} - session mismatch (marker=${_wt_marker_session}, current=${SESSION_ID})"
            _wt_skipped=$((_wt_skipped + 1))
            continue
        fi

        # Validate parent repo path exists
        if [[ -z "$_wt_parent_repo" || ! -d "$_wt_parent_repo" ]]; then
            log "STALE: ${_wt_dir} - parent_repo_path missing or invalid: ${_wt_parent_repo}"
            _wt_skipped=$((_wt_skipped + 1))
            continue
        fi

        # G2b: parent_repo must differ from worktree dir (misconfigured marker guard)
        # If an agent writes the marker from inside the worktree itself (violating
        # SKILL.md), parent_repo_path would equal the worktree path, causing
        # git-worktree-remove to try to remove the parent repo.
        _wt_parent_canon=$(cd "$_wt_parent_repo" 2>/dev/null && pwd -P) || _wt_parent_canon=""
        _wt_dir_canon=$(cd "$_wt_dir" 2>/dev/null && pwd -P) || _wt_dir_canon=""
        if [[ -n "$_wt_parent_canon" && "$_wt_parent_canon" == "$_wt_dir_canon" ]]; then
            log "SKIP: parent_repo == worktree_dir (misconfigured marker): ${_wt_dir}"
            _wt_skipped=$((_wt_skipped + 1))
            continue
        fi

        # Canonicalize _wt_dir to its physical path so symlinks pointing
        # outside WORKTREE_BASE are caught by the case-prefix guard.
        _wt_dir=$(cd "$_wt_dir" 2>/dev/null && pwd -P) || {
            log "STALE: ${_wt_dir} - cannot canonicalize path"
            _wt_skipped=$((_wt_skipped + 1))
            continue
        }

        # Validate worktree path is under WORKTREE_BASE (path traversal guard)
        case "$_wt_dir" in
            "${WORKTREE_BASE}"/*) ;;
            *)
                log "STALE: ${_wt_dir} - path not under ${WORKTREE_BASE}"
                _wt_skipped=$((_wt_skipped + 1))
                continue
                ;;
        esac

        # G3: No uncommitted changes
        if ! git -C "$_wt_dir" diff --quiet 2>/dev/null; then
            log "STALE: ${_wt_dir} - has uncommitted changes"
            _wt_skipped=$((_wt_skipped + 1))
            continue
        fi

        # G4: No staged changes
        if ! git -C "$_wt_dir" diff --cached --quiet 2>/dev/null; then
            log "STALE: ${_wt_dir} - has staged changes"
            _wt_skipped=$((_wt_skipped + 1))
            continue
        fi

        # G5: No untracked files (datasets, generated files not yet git-added)
        _wt_untracked=$(git -C "$_wt_dir" ls-files --others --exclude-standard --directory 2>/dev/null) || _wt_untracked=""
        if [[ -n "$_wt_untracked" ]]; then
            log "SKIP: ${_wt_dir} - untracked files in worktree"
            _wt_skipped=$((_wt_skipped + 1))
            continue
        fi

        # G6: No unpushed commits
        _wt_upstream=$(git -C "$_wt_dir" rev-parse --abbrev-ref '@{u}' 2>/dev/null) || _wt_upstream=""
        if [[ -z "$_wt_upstream" ]]; then
            # No tracking upstream configured — local commits have no remote
            # backup. Treat as unpushed to avoid silent data loss.
            log "STALE: ${_wt_dir} - no upstream configured, local commits may not be backed up"
            _wt_skipped=$((_wt_skipped + 1))
            continue
        fi
        _wt_local=$(git -C "$_wt_dir" rev-parse HEAD 2>/dev/null) || _wt_local=""
        if [[ -z "$_wt_local" ]]; then
            log "STALE: ${_wt_dir} - cannot resolve HEAD"
            _wt_skipped=$((_wt_skipped + 1))
            continue
        fi
        _wt_remote=$(git -C "$_wt_dir" rev-parse '@{u}' 2>/dev/null) || _wt_remote=""
        if [[ -z "$_wt_remote" ]]; then
            log "STALE: ${_wt_dir} - upstream configured but remote ref unavailable"
            _wt_skipped=$((_wt_skipped + 1))
            continue
        fi
        if [[ "$_wt_local" != "$_wt_remote" ]]; then
            log "STALE: ${_wt_dir} - has unpushed commits (local=${_wt_local:0:8} remote=${_wt_remote:0:8})"
            _wt_skipped=$((_wt_skipped + 1))
            continue
        fi

        # G7: Safe removal via git worktree remove from parent repo.
        # No --force: let git refuse if state changed between guards and removal (TOCTOU safety).
        if git -C "$_wt_parent_repo" worktree remove "$_wt_dir" 2>>"$LOG_FILE"; then
            git -C "$_wt_parent_repo" worktree prune 2>>"$LOG_FILE" || true
            log "REMOVED: ${_wt_dir}"
            _wt_removed=$((_wt_removed + 1))
        else
            log "STALE: ${_wt_dir} - git worktree remove failed (see log)"
            _wt_skipped=$((_wt_skipped + 1))
        fi

    done < <(timeout 30 find "$WORKTREE_BASE" -mindepth 2 -maxdepth 10 -name '.claude-session.json' -print0 2>/dev/null)

    if [[ $_wt_candidates -gt 0 ]]; then
        log "Worktree cleanup: ${_wt_candidates} candidates, ${_wt_removed} removed, ${_wt_skipped} skipped"
    fi
    ) &
    # Worktree cleanup is fire-and-forget — not tracked in EMIT_PIDS.
    # Drain logic (below) is for event emission subshells only.
fi

# Drain emit subshells, then stop publisher (OMN-1944)
# SessionEnd has no downstream UI action — waiting is safe here.
# We wait for emit subshells to finish (bounded by timeout) so events
# are enqueued before the publisher is stopped. No fixed-sleep gamble.
DRAIN_TIMEOUT="${PUBLISHER_DRAIN_TIMEOUT_SECONDS:-3}"
if [[ ${#EMIT_PIDS[@]} -gt 0 ]]; then
    # Timeout guard: kill stragglers after DRAIN_TIMEOUT seconds
    ( sleep "$DRAIN_TIMEOUT" && kill "${EMIT_PIDS[@]}" 2>/dev/null ) &
    DRAIN_GUARD_PID=$!
    wait "${EMIT_PIDS[@]}" 2>/dev/null || true
    kill "$DRAIN_GUARD_PID" 2>/dev/null; wait "$DRAIN_GUARD_PID" 2>/dev/null || true
    log "Emit subshells drained (${#EMIT_PIDS[@]} tracked)"
fi

# Stop publisher ONLY if no other Claude Code sessions are still running.
# The publisher is a shared singleton — killing it when other sessions are
# active causes "EVENT EMISSION DEGRADED" failures for every other session.
# Uses pgrep -x for exact process name matching ("claude" only), avoiding
# false positives from Claude Desktop, Cursor, child shells, and pgrep itself.
# Note: -i (case-insensitive) is omitted — it is Linux-only and errors on macOS.
#
# TOCTOU note: there is an inherent race between the pgrep count and the
# publisher stop — another session could start or stop in the gap. This is
# acceptable: premature kill is recovered by SessionStart (idempotent restart),
# and leaving the publisher running is harmless (next SessionEnd cleans it up).
#
# Binary name assumption: pgrep -x "claude" assumes the CLI binary is named
# exactly "claude". If renamed (e.g. "claude-code"), the count will always be 0,
# causing publisher stop on every SessionEnd — safe (SessionStart restarts) but
# suboptimal.
#
# Fail-safe semantics: if pgrep itself errors (exit >=2: permission denied,
# syntax error, /proc unavailable), we default to 9999 so the publisher stays
# alive. Rationale: a missed stop is harmless (next SessionEnd retries or the
# daemon idles out), but a false stop disrupts every other active session.
#
# pgrep exit codes: 0 = matched, 1 = no matches (normal), 2+ = real error.
# With pipefail, we must capture pgrep's exit code separately — otherwise
# exit 1 (no matches) and exit 2 (error) are both treated as pipeline failure.
_pgrep_rc=0
_pgrep_output=$(pgrep -x "claude" 2>/dev/null) || _pgrep_rc=$?
if [[ $_pgrep_rc -ge 2 ]]; then
    # Real pgrep failure — cannot determine session count; keep publisher alive
    _other_claude_sessions=9999
    log "WARNING: pgrep failed (exit=$_pgrep_rc), assuming other sessions exist (fail-safe)"
elif [[ $_pgrep_rc -eq 1 ]]; then
    # No matches — zero claude processes running
    _other_claude_sessions=0
else
    # Success — count matched PIDs (one per line)
    _other_claude_sessions=$(echo "$_pgrep_output" | wc -l | tr -d ' ')
fi
if [[ "$_other_claude_sessions" -le 1 ]]; then
    # 1 or fewer = only this session (pgrep -x never matches itself); safe to stop
    "$PYTHON_CMD" -m omniclaude.publisher stop >> "$LOG_FILE" 2>&1 || {
        # Fallback: try legacy daemon stop
        "$PYTHON_CMD" -m omnibase_infra.runtime.emit_daemon.cli stop >> "$LOG_FILE" 2>&1 || true
    }
    log "Publisher stop signal sent (last session)"
else
    log "Publisher kept alive (${_other_claude_sessions} Claude processes still running)"
fi

log "SessionEnd hook completed"
# No explicit `wait` needed before exit: emit subshells are already drained
# above (line "wait ${EMIT_PIDS[@]}"), and the worktree cleanup subshell is
# fire-and-forget (reparented to init on exit). Bash does not send SIGHUP
# to backgrounded jobs on non-interactive shell exit.
exit 0
