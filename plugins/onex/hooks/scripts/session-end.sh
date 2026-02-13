#!/bin/bash
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
    log "Phase 1: tools_used_count absent or zero — SUCCESS gate unreachable (see OMN-1892)"
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
    # Sanitize: ensure SESSION_DURATION is strictly numeric before awk
    [[ "$SESSION_DURATION" =~ ^[0-9]+$ ]] || SESSION_DURATION=0
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
        # Validate SESSION_ID once for all outcome/feedback work
        if [[ -z "$SESSION_ID" ]]; then
            log "WARNING: SESSION_ID is empty, skipping session.outcome and feedback"
            exit 0
        fi

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

        # --- Evaluate feedback guardrails ---
        # ===================================================================
        # PHASE 1 PLUMBING (OMN-1892): Guardrail logic is wired but inputs
        # are hardcoded. Feedback will always be skipped (NO_INJECTION).
        # Future tickets to wire real values:
        #   - injection_occurred: Read from session injection marker
        #   - utilization_score: Read from PostToolUse utilization metrics
        #   - agent_match_score: Read from UserPromptSubmit routing decision
        # ===================================================================
        FEEDBACK_RESULT=$(HOOKS_LIB="$HOOKS_LIB" DERIVED_OUTCOME="$DERIVED_OUTCOME" \
            "$PYTHON_CMD" -c "
import os, sys, json
sys.path.insert(0, os.environ['HOOKS_LIB'])
from feedback_guardrails import should_reinforce_routing
result = should_reinforce_routing(
    injection_occurred=False,
    utilization_score=0.0,
    agent_match_score=0.0,
    session_outcome=os.environ['DERIVED_OUTCOME'],
)
print(json.dumps({
    'should_reinforce': result.should_reinforce,
    'skip_reason': result.skip_reason,
}))
" 2>>"$LOG_FILE") || FEEDBACK_RESULT='{"should_reinforce":false,"skip_reason":"PYTHON_ERROR"}'

        SHOULD_REINFORCE=$(echo "$FEEDBACK_RESULT" | jq -r '.should_reinforce' 2>>"$LOG_FILE") || SHOULD_REINFORCE="false"
        SKIP_REASON=$(echo "$FEEDBACK_RESULT" | jq -r '.skip_reason // empty' 2>>"$LOG_FILE") || SKIP_REASON=""

        if [[ "$SHOULD_REINFORCE" == "true" ]] && [[ "$KAFKA_ENABLED" == "true" ]]; then
            if ! FEEDBACK_PAYLOAD=$(jq -n \
                --arg session_id "$SESSION_ID" \
                --arg outcome "$DERIVED_OUTCOME" \
                --arg emitted_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
                '{session_id: $session_id, outcome: $outcome, emitted_at: $emitted_at}' 2>>"$LOG_FILE"); then
                log "WARNING: Failed to construct routing.feedback payload (jq failed), skipping emission"
                exit 0
            fi

            if [[ -n "$FEEDBACK_PAYLOAD" && "$FEEDBACK_PAYLOAD" != "null" ]]; then
                emit_via_daemon "routing.feedback" "$FEEDBACK_PAYLOAD" 100
            fi
        elif [[ -n "$SKIP_REASON" ]] && [[ "$KAFKA_ENABLED" == "true" ]]; then
            if ! SKIP_PAYLOAD=$(jq -n \
                --arg session_id "$SESSION_ID" \
                --arg skip_reason "$SKIP_REASON" \
                --arg emitted_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
                '{session_id: $session_id, skip_reason: $skip_reason, emitted_at: $emitted_at}' 2>>"$LOG_FILE"); then
                log "WARNING: Failed to construct routing.skipped payload (jq failed), skipping emission"
                exit 0
            fi

            if [[ -z "$SKIP_PAYLOAD" || "$SKIP_PAYLOAD" == "null" ]]; then
                log "WARNING: routing.skipped payload empty or null, skipping emission"
            else
                emit_via_daemon "routing.skipped" "$SKIP_PAYLOAD" 100
            fi
        fi

        log "Feedback guardrail: should_reinforce=$SHOULD_REINFORCE skip_reason=$SKIP_REASON"
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
# Worktree Cleanup (OMN-1856)
# -----------------------------
# Clean up agent-created worktrees from this session.
# Only targets ~/.claude/worktrees/ with valid .claude-session.json markers.
# Uses git worktree remove (never rm -rf). Idempotent.

WORKTREE_BASE="${HOME}/.claude/worktrees"

if [[ -d "$WORKTREE_BASE" ]]; then
    _wt_candidates=0
    _wt_removed=0
    _wt_skipped=0

    # Scan two levels deep: ~/.claude/worktrees/{repo}/{branch}/
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

        # G5: No unpushed commits
        _wt_upstream=$(git -C "$_wt_dir" rev-parse --abbrev-ref '@{u}' 2>/dev/null) || _wt_upstream=""
        if [[ -n "$_wt_upstream" ]]; then
            _wt_local=$(git -C "$_wt_dir" rev-parse HEAD 2>/dev/null) || _wt_local=""
            _wt_remote=$(git -C "$_wt_dir" rev-parse '@{u}' 2>/dev/null) || _wt_remote=""
            if [[ -n "$_wt_local" && -n "$_wt_remote" && "$_wt_local" != "$_wt_remote" ]]; then
                log "STALE: ${_wt_dir} - has unpushed commits (local=${_wt_local:0:8} remote=${_wt_remote:0:8})"
                _wt_skipped=$((_wt_skipped + 1))
                continue
            fi
        fi

        # G6: Safe removal via git worktree remove from parent repo
        if git -C "$_wt_parent_repo" worktree remove --force "$_wt_dir" 2>>"$LOG_FILE"; then
            git -C "$_wt_parent_repo" worktree prune 2>>"$LOG_FILE" || true
            log "REMOVED: ${_wt_dir}"
            _wt_removed=$((_wt_removed + 1))
        else
            log "STALE: ${_wt_dir} - git worktree remove failed (see log)"
            _wt_skipped=$((_wt_skipped + 1))
        fi

    done < <(find "$WORKTREE_BASE" -mindepth 3 -maxdepth 3 -name '.claude-session.json' -print0 2>/dev/null)

    if [[ $_wt_candidates -gt 0 ]]; then
        log "Worktree cleanup: ${_wt_candidates} candidates, ${_wt_removed} removed, ${_wt_skipped} skipped"
    fi
fi

# Output response immediately so Claude Code can proceed with shutdown
echo "$INPUT"

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

# Stop publisher after all events are enqueued (or timed out)
"$PYTHON_CMD" -m omniclaude.publisher stop >> "$LOG_FILE" 2>&1 || {
    # Fallback: try legacy daemon stop
    "$PYTHON_CMD" -m omnibase_infra.runtime.emit_daemon.cli stop >> "$LOG_FILE" 2>&1 || true
}
log "Publisher stop signal sent"

log "SessionEnd hook completed"
exit 0
