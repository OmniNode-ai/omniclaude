# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Track fix attempts per friction surface for two-strike rule enforcement.

Persists to `.onex_state/friction-fix-attempts.json`.
A surface is blocked after 2 failed attempts.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_STATE_PATH = (
    Path.home() / ".claude" / ".onex_state" / "friction-fix-attempts.json"
)
_MAX_ATTEMPTS = 2


class AttemptTracker:
    """Tracks fix attempts per surface_key with persistence."""

    def __init__(self, *, state_path: Path | None = None) -> None:
        self._path = state_path or _DEFAULT_STATE_PATH
        self._data: dict[str, dict[str, int | str]] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                logger.debug("attempt_tracker: load failed: %s", exc)
                self._data = {}

    def save(self) -> None:
        """Persist current state to disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    def get_attempt_count(self, surface_key: str) -> int:
        """Return the number of fix attempts for a surface_key."""
        entry = self._data.get(surface_key, {})
        return int(entry.get("attempts", 0))

    def is_blocked(self, surface_key: str) -> bool:
        """Return True if surface_key has reached the two-strike limit."""
        return self.get_attempt_count(surface_key) >= _MAX_ATTEMPTS

    def record_attempt(self, surface_key: str) -> None:
        """Record a fix attempt for a surface_key. Auto-saves."""
        if surface_key not in self._data:
            self._data[surface_key] = {"attempts": 0, "last_attempt": ""}
        self._data[surface_key]["attempts"] = (
            int(self._data[surface_key].get("attempts", 0)) + 1
        )
        self._data[surface_key]["last_attempt"] = datetime.now(UTC).isoformat()
        self.save()

    def mark_resolved(self, surface_key: str) -> None:
        """Clear attempt tracking for a resolved surface_key. Auto-saves."""
        if surface_key in self._data:
            del self._data[surface_key]
            self.save()
