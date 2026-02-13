#!/usr/bin/env python3
"""Session State Adapter - CLI interface orchestrating effect + reducer nodes.

G3 node: Declarative command registry. Fail-open on all errors.

CLI Usage:
    echo '{"sessionId": "..."}' | python3 node_session_state_adapter.py init
    echo '{"run_id": "..."}' | python3 node_session_state_adapter.py end
    echo '{"run_id": "..."}' | python3 node_session_state_adapter.py set-active-run

Note: stdin keys accept both camelCase (Claude Code native) and snake_case forms.
    sessionId / session_id, runId / run_id are all recognized.

All commands:
    - Read JSON from stdin
    - Output JSON to stdout
    - Log errors to stderr
    - Exit 0 always (fail-open)

Related Tickets:
    - OMN-2119: Session State Orchestrator Shim + Adapter

.. versionadded:: 0.2.1
"""

from __future__ import annotations

import json
import sys
import uuid
from collections.abc import Callable
from datetime import UTC, datetime


def _now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(UTC).isoformat()


def _read_stdin() -> dict:
    """Read JSON from stdin, returning empty dict on any failure."""
    try:
        raw = sys.stdin.read().strip()
        if not raw:
            return {}
        data = json.loads(raw)
        if not isinstance(data, dict):
            return {}
        return data
    except Exception:
        return {}


def _output(data: dict) -> None:
    """Write JSON to stdout."""
    print(json.dumps(data))


def _get_key(data: dict, snake: str, camel: str, default: str = "") -> str:
    """Get a value by snake_case or camelCase key.

    Claude Code pipes raw JSON with camelCase keys (sessionId, projectPath),
    but internal callers may use snake_case. Accept both forms defensively.
    """
    return data.get(snake) or data.get(camel) or default


# =============================================================================
# Command Handlers
# =============================================================================


def cmd_init(stdin_data: dict) -> dict:
    """Initialize a new run.

    Reads session_id from stdin, creates run doc, transitions through FSM,
    updates session index atomically with flock, triggers GC check.

    Returns:
        {"run_id": "...", "state": "run_active"} on success, {} on failure.
    """
    # Import here to allow the adapter to be imported without side effects
    from node_session_lifecycle_reducer import Event, State, reduce
    from node_session_state_effect import (
        ContractRunContext,
        LockResult,
        gc_stale_runs,
        update_session_index,
        write_run_context,
    )

    session_id = _get_key(stdin_data, "session_id", "sessionId")
    if not session_id:
        print("WARNING: No session_id/sessionId provided in stdin", file=sys.stderr)
        return {}

    run_id = str(uuid.uuid4())
    now = _now_iso()

    # Transition: IDLE -> RUN_CREATED -> RUN_ACTIVE
    state = State.IDLE
    state = reduce(state, Event.CREATE_RUN)
    state = reduce(state, Event.ACTIVATE_RUN)

    # Create run context document
    ctx = ContractRunContext(
        run_id=run_id,
        session_id=session_id,
        state=state.value,
        created_at=now,
        updated_at=now,
    )
    write_run_context(ctx)

    # Atomic read-modify-write of session index (eliminates TOCTOU race)
    def _mutate_init(index):
        index.active_run_id = run_id
        if run_id not in index.recent_run_ids:
            index.recent_run_ids.insert(0, run_id)
            # Keep only last 20 run IDs
            index.recent_run_ids = index.recent_run_ids[:20]
        index.updated_at = now
        return index

    lock_result = update_session_index(_mutate_init)
    if lock_result != LockResult.ACQUIRED:
        print(
            f"WARNING: Lock {lock_result.value} writing session index", file=sys.stderr
        )
        # Run doc was already written; index update failed — orphan run doc.
        # Best-effort cleanup: delete the orphan run doc so it doesn't sit on
        # disk until GC catches it (~28 hours at 7x orphan TTL).
        print(f"WARNING: Orphan run doc {run_id}, attempting cleanup", file=sys.stderr)
        try:
            from node_session_state_effect import delete_run_context

            deleted = delete_run_context(run_id)
            if not deleted:
                print(
                    f"WARNING: Orphan run doc {run_id} not found or already removed",
                    file=sys.stderr,
                )
        except Exception as cleanup_err:
            print(
                f"WARNING: Failed to clean orphan run doc {run_id}: {cleanup_err}",
                file=sys.stderr,
            )
        return {}

    # Time-gated GC check (only on init)
    try:
        gc_stale_runs()
    except Exception as e:
        print(f"WARNING: GC failed: {e}", file=sys.stderr)

    return {"run_id": run_id, "state": state.value}


def cmd_end(stdin_data: dict) -> dict:
    """End a run.

    Reads run_id from stdin, transitions to run_ended, updates run doc.
    Does NOT delete the run doc (GC handles cleanup).

    Returns:
        {"run_id": "...", "state": "run_ended"} on success, {} on failure.
    """
    from node_session_lifecycle_reducer import (
        Event,
        InvalidTransitionError,
        State,
        reduce,
    )
    from node_session_state_effect import (
        read_run_context,
        update_session_index,
        write_run_context,
    )

    run_id = _get_key(stdin_data, "run_id", "runId")
    if not run_id:
        print("WARNING: No run_id/runId provided in stdin", file=sys.stderr)
        return {}

    # Note: concurrent cmd_end on same run_id is benign (both write
    # run_ended, last-writer-wins on updated_at).
    ctx = read_run_context(run_id)
    if ctx is None:
        print(f"WARNING: Run context not found for {run_id}", file=sys.stderr)
        return {}

    # Resolve current state from the stored value
    try:
        current_state = State(ctx.state)
    except ValueError:
        print(f"WARNING: Unknown state '{ctx.state}' for run {run_id}", file=sys.stderr)
        return {}

    # Transition: RUN_ACTIVE -> RUN_ENDED
    try:
        next_state = reduce(current_state, Event.END_RUN)
    except InvalidTransitionError as e:
        print(f"Warning: {e}", file=sys.stderr)
        return {}

    ctx.state = next_state.value
    ctx.updated_at = _now_iso()
    write_run_context(ctx)

    # Best-effort: clear active_run_id if it references the ended run.
    # Uses atomic read-modify-write to avoid TOCTOU races. Lock timeout
    # is acceptable — the run doc is already in run_ended state and GC
    # will eventually clean up the stale active_run_id reference.
    try:
        now = _now_iso()

        def _mutate_clear_active(index):
            if index.active_run_id == run_id:
                index.active_run_id = None
                index.updated_at = now
            return index

        update_session_index(_mutate_clear_active)
    except Exception as e:
        print(
            f"WARNING: Failed to clear active_run_id for {run_id}: {e}", file=sys.stderr
        )

    return {"run_id": run_id, "state": next_state.value}


def cmd_set_active_run(stdin_data: dict) -> dict:
    """Set the active run ID in the session index.

    Reads run_id from stdin, validates non-empty, atomically updates session.json.

    Returns:
        {"active_run_id": "..."} on success, {} on failure.
    """
    from node_session_state_effect import (
        LockResult,
        read_run_context,
        update_session_index,
    )

    run_id = _get_key(stdin_data, "run_id", "runId")
    if not run_id:
        print("WARNING: No run_id/runId provided in stdin", file=sys.stderr)
        return {}

    # Validate that run_id corresponds to an existing run context (fail-open)
    existing = read_run_context(run_id)
    if not existing:
        print(
            f"Warning: run context for {run_id} not found, setting active anyway",
            file=sys.stderr,
        )

    # Atomic read-modify-write of session index (eliminates TOCTOU race)
    now = _now_iso()

    def _mutate_set_active(index):
        index.active_run_id = run_id
        index.updated_at = now
        return index

    lock_result = update_session_index(_mutate_set_active)
    if lock_result != LockResult.ACQUIRED:
        print(
            f"WARNING: Lock {lock_result.value} writing session index", file=sys.stderr
        )
        return {}

    return {"active_run_id": run_id}


# =============================================================================
# Command Registry
# =============================================================================

COMMANDS: dict[str, Callable[[dict], dict]] = {
    "init": cmd_init,
    "end": cmd_end,
    "set-active-run": cmd_set_active_run,
}


# =============================================================================
# CLI Entry Point
# =============================================================================


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Always returns 0 (fail-open).

    Args:
        argv: Command line arguments (defaults to sys.argv[1:]).

    Returns:
        Exit code (always 0).
    """
    args = argv if argv is not None else sys.argv[1:]

    if not args:
        print("Usage: node_session_state_adapter.py <command>", file=sys.stderr)
        print(f"Commands: {', '.join(sorted(COMMANDS))}", file=sys.stderr)
        _output({})
        return 0

    command = args[0]
    handler = COMMANDS.get(command)

    if handler is None:
        print(f"Unknown command: {command}", file=sys.stderr)
        _output({})
        return 0

    try:
        stdin_data = _read_stdin()
        result = handler(stdin_data)
        _output(result)
    except Exception as e:
        # Fail-open: catch ALL exceptions, log to stderr, output empty JSON
        print(f"ERROR: {command} failed: {e}", file=sys.stderr)
        _output({})

    return 0


if __name__ == "__main__":
    sys.exit(main())
