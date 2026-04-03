#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""CLI entry point for the watchdog reducer.

Thin shell over the pure reducer — handles file I/O, timestamps, UUIDs,
and translates intents to exit codes + JSON output.

This script is called by the bash watchdog scripts. It is NOT the reducer
itself — the reducer is in omniclaude.shared.models.model_watchdog_state.

Usage:
    # Record a run result (writes state, prints intent JSON)
    python3 watchdog_reducer_cli.py run <loop> <result> <phase> [error_message]

    # Check escalation level (reads state, prints check result JSON)
    python3 watchdog_reducer_cli.py check <loop>

    # Record an action taken (writes state)
    python3 watchdog_reducer_cli.py action <loop> <action> <detail>

    # Read state (prints state JSON for a loop)
    python3 watchdog_reducer_cli.py read <loop>

Exit codes match the escalation policy (0=restart, 2=investigate, etc.)
"""

from __future__ import annotations

import fcntl
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

# Add the src directory to sys.path so we can import the module directly
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from omniclaude.shared.models.model_watchdog_state import (  # noqa: E402
    EnumRunResult,
    EnumWatchdogEventKind,
    ModelWatchdogEvent,
    check_escalation,
    load_policy,
    load_state,
    reduce,
    save_state,
)

OMNI_HOME = Path(
    __import__("os").environ.get("OMNI_HOME", str(Path.home() / "omni_home"))
)
STATE_DIR = OMNI_HOME / ".onex_state" / "watchdog"


def _apply_event_with_lock(
    event: ModelWatchdogEvent, policy: object
) -> tuple[object, list[object]]:
    """Serialize reducer writes across processes via fcntl file lock."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    lock_file = STATE_DIR / ".watchdog.lock"
    with lock_file.open("a+") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        state = load_state(STATE_DIR)
        new_state, intents = reduce(state, event, policy)
        save_state(new_state, STATE_DIR)
    return new_state, intents


def cmd_run(args: list[str]) -> int:
    """Record a run result via the reducer."""
    if len(args) < 3:
        print(
            "Usage: watchdog_reducer_cli.py run <loop> <result> <phase> [error_message]",
            file=sys.stderr,
        )
        return 1

    loop_name, result, phase = args[0], args[1], args[2]
    error_msg = args[3] if len(args) > 3 else None

    if loop_name not in ("closeout", "buildloop"):
        print(
            f"ERROR: loop must be 'closeout' or 'buildloop', got '{loop_name}'",
            file=sys.stderr,
        )
        return 1
    if result not in ("pass", "fail"):
        print(
            f"ERROR: result must be 'pass' or 'fail', got '{result}'", file=sys.stderr
        )
        return 1

    policy = load_policy()

    event = ModelWatchdogEvent(
        kind=EnumWatchdogEventKind.RUN_COMPLETED,
        loop=loop_name,
        result=EnumRunResult(result),
        phase=phase,
        error_message=error_msg[:200] if error_msg else None,
        timestamp=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        correlation_id=str(uuid.uuid4()),
    )

    new_state, intents = _apply_event_with_lock(event, policy)

    level = new_state.loops[loop_name].escalation_level
    print(
        f"Watchdog state updated: loop={loop_name} result={result} phase={phase} escalation={level}"
    )

    if intents:
        intent = intents[0]
        print(json.dumps(intent.model_dump(mode="json")))

    return 0


def cmd_check(args: list[str]) -> int:
    """Check escalation level — returns exit code matching the policy."""
    if len(args) < 1:
        print("Usage: watchdog_reducer_cli.py check <loop>", file=sys.stderr)
        return 1

    loop_name = args[0]
    if loop_name not in ("closeout", "buildloop"):
        print(
            f"ERROR: loop must be 'closeout' or 'buildloop', got '{loop_name}'",
            file=sys.stderr,
        )
        return 1

    policy = load_policy()
    state = load_state(STATE_DIR)
    result = check_escalation(state, loop_name, policy=policy)

    print(json.dumps(result.model_dump(mode="json"), indent=2))
    return result.exit_code


def cmd_action(args: list[str]) -> int:
    """Record an action taken."""
    if len(args) < 3:
        print(
            "Usage: watchdog_reducer_cli.py action <loop> <action> <detail>",
            file=sys.stderr,
        )
        return 1

    loop_name, action, detail = args[0], args[1], args[2]

    if loop_name not in ("closeout", "buildloop"):
        print(
            f"ERROR: loop must be 'closeout' or 'buildloop', got '{loop_name}'",
            file=sys.stderr,
        )
        return 1

    policy = load_policy()

    event = ModelWatchdogEvent(
        kind=EnumWatchdogEventKind.ACTION_TAKEN,
        loop=loop_name,
        action=action,
        detail=detail[:200],
        timestamp=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        correlation_id=str(uuid.uuid4()),
    )

    _new_state, _intents = _apply_event_with_lock(event, policy)

    print(f"Recorded action: {action} for {loop_name}")
    return 0


def cmd_read(args: list[str]) -> int:
    """Read state for a loop."""
    if len(args) < 1:
        print("Usage: watchdog_reducer_cli.py read <loop>", file=sys.stderr)
        return 1

    loop_name = args[0]

    if loop_name not in ("closeout", "buildloop"):
        print(
            f"ERROR: loop must be 'closeout' or 'buildloop', got '{loop_name}'",
            file=sys.stderr,
        )
        return 1

    state = load_state(STATE_DIR)

    if loop_name in state.loops:
        print(json.dumps(state.loops[loop_name].model_dump(mode="json"), indent=2))
    else:
        print(
            json.dumps(
                {
                    "runs": [],
                    "failure_streaks": {},
                    "escalation_level": 0,
                    "actions_taken": [],
                    "fsm_state": "healthy",
                }
            )
        )
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print(
            "Usage: watchdog_reducer_cli.py <run|check|action|read> ...",
            file=sys.stderr,
        )
        return 1

    cmd = sys.argv[1]
    args = sys.argv[2:]

    commands = {
        "run": cmd_run,
        "check": cmd_check,
        "action": cmd_action,
        "read": cmd_read,
    }

    handler = commands.get(cmd)
    if handler is None:
        print(f"Unknown command: {cmd}. Use: run, check, action, read", file=sys.stderr)
        return 1

    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
