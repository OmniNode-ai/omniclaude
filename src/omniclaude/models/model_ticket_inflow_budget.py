# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Strict, stdlib-only measurement exchanged by the sweep and admission hook."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NamedTuple


def timestamp(value: str) -> datetime:
    """Parse an aware ISO timestamp; naive times cannot define a budget window."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("budget timestamps must carry a timezone")
    return parsed.astimezone(UTC)


class ModelTicketInflowBudget(NamedTuple):
    """Counts from an exhausted enumeration, never an inferred daily allowance.

    ``closed_count`` counts completed (not canceled) tickets behind the governed
    Done-write path. ``lane_created_count`` includes all hosts visible to Linear.
    The admission journal adds creates admitted since this snapshot, including
    creates whose subsequent Linear write failed.
    """

    created_count: int
    closed_count: int
    lane_created_count: int
    window: dict[str, str]

    @classmethod
    def from_dict(cls, raw: object) -> ModelTicketInflowBudget:
        """Reject absent fields, partial windows, coercions and impossible counts."""
        if not isinstance(raw, dict):
            raise ValueError("inflow budget must be an object")
        counts = [
            raw[k] for k in ("created_count", "closed_count", "lane_created_count")
        ]
        if any(type(count) is not int or count < 0 for count in counts):
            raise ValueError("inflow counts must be nonnegative integers")
        if counts[2] > counts[0]:
            raise ValueError("lane-created count exceeds total created count")
        window = raw["window"]
        if not isinstance(window, dict) or set(window) != {"start", "end"}:
            raise ValueError("budget window requires start and end")
        if not all(isinstance(value, str) for value in window.values()):
            raise ValueError("budget window timestamps must be strings")
        if timestamp(window["start"]) >= timestamp(window["end"]):
            raise ValueError("budget window must have positive duration")
        return cls(counts[0], counts[1], counts[2], dict(window))

    def validate_window(self, now: datetime, days: int, max_age_seconds: int) -> None:
        """Refuse stale, future or differently scoped measurements."""
        end = timestamp(self.window["end"])
        if end - timestamp(self.window["start"]) != timedelta(days=days):
            raise ValueError("budget window does not match policy.window_days")
        age = (now - end).total_seconds()
        if age < 0 or age > max_age_seconds:
            raise ValueError("budget is stale or future-dated")

    def write(self, path: Path) -> None:
        """Validate and replace atomically; a failed sweep leaves the old file."""
        self.from_dict(self._asdict())
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".inflow-", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(self._asdict(), stream)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            Path(temporary).replace(path)
        finally:
            Path(temporary).unlink(missing_ok=True)
