# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Idle notification rate limiter — 60s sliding window per agent_id (OMN-8924).

Reads and writes a JSON state file at $ONEX_STATE_DIR/idle_ratelimit.json.
State schema: {"<agent_id>": <last_sent_unix_timestamp>}
"""

from __future__ import annotations

import json
import time
from pathlib import Path

_WINDOW_SECONDS = 60
_STATE_FILENAME = "idle_ratelimit.json"


def _state_path() -> Path:
    from onex_state import ensure_state_path  # noqa: PLC0415

    return ensure_state_path(_STATE_FILENAME)


def should_allow_idle_notification(agent_id: str, *, now: float | None = None) -> bool:
    """Return True if the idle_notification may proceed; False if it should be dropped.

    A notification is allowed when no previous notification was sent within the last
    WINDOW_SECONDS for this agent_id. On allow, updates the state file timestamp.
    """
    ts = now if now is not None else time.time()
    state_file = _state_path()

    state: dict[str, float] = {}
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text())
        except (json.JSONDecodeError, OSError):
            state = {}

    last_sent = state.get(agent_id)
    if last_sent is not None and (ts - last_sent) < _WINDOW_SECONDS:
        return False

    state[agent_id] = ts
    try:
        state_file.write_text(json.dumps(state))
    except OSError:
        pass
    return True
