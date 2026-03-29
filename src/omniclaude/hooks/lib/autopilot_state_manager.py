# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Autopilot state persistence, mutex, and strike tracking.

Covers OMN-6491 (cycle state), OMN-6492 (mutex), OMN-6505 (strike tracker).

State file: .onex_state/autopilot-cycle.yaml
Lock file:  .onex_state/autopilot.lock

The mutex uses a file-based lock with PID and timestamp for stale detection.
Locks older than 2 hours are considered stale and can be reclaimed.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from omniclaude.shared.models.model_autopilot_cycle_state import (
    ModelAutopilotCycleState,
)

logger = logging.getLogger(__name__)

_CYCLE_STATE_FILE = "autopilot-cycle.yaml"
_LOCK_FILE = "autopilot.lock"
_STALE_LOCK_SECONDS = 2 * 60 * 60  # 2 hours


def save_cycle_state(state: ModelAutopilotCycleState) -> Path:
    """Persist cycle state to .onex_state/autopilot-cycle.yaml.

    Returns the path written to.
    """
    from omniclaude.hooks.lib.onex_state import ensure_state_path  # noqa: PLC0415

    path = ensure_state_path(_CYCLE_STATE_FILE)
    data = state.model_dump(mode="json")
    path.write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")
    return path


def load_cycle_state() -> ModelAutopilotCycleState | None:
    """Load cycle state from disk, or None if not present / corrupt."""
    from omniclaude.hooks.lib.onex_state import state_path  # noqa: PLC0415

    path = state_path(_CYCLE_STATE_FILE)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return ModelAutopilotCycleState.model_validate(data)
    except Exception:  # noqa: BLE001
        logger.warning("Failed to load autopilot cycle state from %s", path)
        return None


# ---------------------------------------------------------------------------
# Mutex (OMN-6492)
# ---------------------------------------------------------------------------


class AutopilotMutexError(RuntimeError):
    """Raised when the autopilot mutex cannot be acquired."""


class AutopilotMutex:
    """File-based mutex for autopilot cycle exclusion.

    Lock file contains JSON with PID, timestamp, and run_id.
    Stale locks (>2 hours) are automatically reclaimed.

    Usage::

        mutex = AutopilotMutex()
        mutex.acquire(run_id="abc-123")
        try:
            ...  # run autopilot
        finally:
            mutex.release()
    """

    def __init__(self, stale_seconds: float = _STALE_LOCK_SECONDS) -> None:
        self._stale_seconds = stale_seconds
        self._lock_path: Path | None = None

    def _resolve_lock_path(self) -> Path:
        from omniclaude.hooks.lib.onex_state import ensure_state_path  # noqa: PLC0415

        return ensure_state_path(_LOCK_FILE)

    def acquire(self, run_id: str) -> None:
        """Acquire the mutex. Raises AutopilotMutexError if already held."""
        lock_path = self._resolve_lock_path()

        if lock_path.exists():
            try:
                existing = json.loads(lock_path.read_text(encoding="utf-8"))
                lock_ts = existing.get("timestamp", 0)
                lock_pid = existing.get("pid", -1)
                age = time.time() - lock_ts

                if age < self._stale_seconds and _pid_alive(lock_pid):
                    msg = (
                        f"Autopilot mutex held by PID {lock_pid} "
                        f"(run_id={existing.get('run_id', '?')}, "
                        f"age={age:.0f}s). Cannot acquire."
                    )
                    raise AutopilotMutexError(msg)

                logger.info(
                    "Reclaiming stale autopilot lock (pid=%s, age=%.0fs)",
                    lock_pid,
                    age,
                )
            except (json.JSONDecodeError, KeyError):
                logger.warning("Corrupt lock file at %s — reclaiming", lock_path)

        lock_data = {
            "pid": os.getpid(),
            "timestamp": time.time(),
            "run_id": run_id,
            "acquired_at": datetime.now(UTC).isoformat(),
        }
        lock_path.write_text(json.dumps(lock_data, indent=2) + "\n", encoding="utf-8")
        self._lock_path = lock_path

    def release(self) -> None:
        """Release the mutex by removing the lock file."""
        lock_path = self._lock_path or self._resolve_lock_path()
        if lock_path.exists():
            lock_path.unlink(missing_ok=True)
            logger.info("Autopilot mutex released")
        self._lock_path = None

    def is_locked(self) -> bool:
        """Check if the mutex is currently held (non-stale)."""
        lock_path = self._resolve_lock_path()
        if not lock_path.exists():
            return False
        try:
            existing = json.loads(lock_path.read_text(encoding="utf-8"))
            lock_ts = existing.get("timestamp", 0)
            lock_pid = existing.get("pid", -1)
            age = time.time() - lock_ts
            return age < self._stale_seconds and _pid_alive(lock_pid)
        except (json.JSONDecodeError, KeyError):
            return False


def _pid_alive(pid: int) -> bool:
    """Check if a process is alive. Returns False for invalid PIDs."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # process exists but we can't signal it
    return True


__all__ = [
    "AutopilotMutex",
    "AutopilotMutexError",
    "load_cycle_state",
    "save_cycle_state",
]
