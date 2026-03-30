# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Manages ONEX_TASK_ID binding for cross-session correlation.

Dual persistence per Doctrine D1:
  - ``.onex_state/active_session.yaml`` is the authoritative local binding record.
  - ``os.environ["ONEX_TASK_ID"]`` is an in-process runtime convenience derived
    from that binding (hooks read this env var when building payloads).

The state file is primary; the env var is secondary.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import yaml


class TaskBinding:
    """Bind/unbind the current session to a Linear ticket ID.

    Parameters
    ----------
    state_dir:
        Root directory for ``.onex_state/``.  Defaults to the current working
        directory when ``None``.
    """

    _ENV_KEY = "ONEX_TASK_ID"
    _STATE_SUBDIR = ".onex_state"
    _STATE_FILENAME = "active_session.yaml"

    def __init__(self, state_dir: Path | None = None) -> None:
        self._state_dir = state_dir or Path.cwd()

    @property
    def _state_file(self) -> Path:
        return self._state_dir / self._STATE_SUBDIR / self._STATE_FILENAME

    def bind(self, task_id: str) -> None:
        """Bind the session to *task_id*.

        Writes the authoritative state file and sets the convenience env var.

        Raises
        ------
        ValueError
            If *task_id* is empty or whitespace-only.
        """
        if not task_id or not task_id.strip():
            msg = "task_id must be a non-empty string"
            raise ValueError(msg)

        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "task_id": task_id,
            "bound_at": datetime.now(tz=UTC).isoformat(),
        }
        self._state_file.write_text(yaml.safe_dump(payload, sort_keys=False))
        os.environ[self._ENV_KEY] = task_id

    def clear(self) -> None:
        """Remove the binding — both state file and env var."""
        if self._state_file.exists():
            self._state_file.unlink()
        os.environ.pop(self._ENV_KEY, None)

    def detect_existing(self) -> str | None:
        """Read the state file and return the bound task_id, or ``None``."""
        if not self._state_file.exists():
            return None
        try:
            content = yaml.safe_load(self._state_file.read_text())
            return content.get("task_id") if isinstance(content, dict) else None
        except (yaml.YAMLError, OSError):
            return None
