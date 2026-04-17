# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Idle notification rate limiter — 60s sliding window per agent_id (OMN-8924).

Reads and writes a JSON state file at $ONEX_STATE_DIR/idle_ratelimit.json.
State schema: {"<agent_id>": <last_sent_unix_timestamp>}

Cross-process safety: an exclusive fcntl lock on a companion .lock file serialises
all read/modify/write cycles. The updated state is written atomically via a temp
file + os.replace so readers never see a partial write.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
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
    lock_file = state_file.with_suffix(".lock")

    lock_fd = os.open(str(lock_file), os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

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
            dir_ = state_file.parent
            with tempfile.NamedTemporaryFile(
                mode="w", dir=dir_, delete=False, suffix=".tmp"
            ) as tmp:
                json.dump(state, tmp)
                tmp_path = tmp.name
            Path(tmp_path).replace(state_file)
        except OSError:
            pass
        return True
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
