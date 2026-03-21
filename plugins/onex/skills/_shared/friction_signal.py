# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Portable friction signal — zero ONEX dependencies.

This dataclass represents a raw failure signal from any source (Claude Code,
Cursor, Codex, Kafka consumer). It carries no ONEX-specific imports so that
non-ONEX integrations can construct signals without pulling in the platform.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class FrictionSignal:
    """A raw failure signal from any agent platform or event source."""

    source: str
    """Origin identifier: 'claude_code_hook', 'cursor', 'codex', 'kafka_consumer', etc."""

    event_type: str
    """Semantic event key: 'skill.completed', 'circuit.breaker.tripped', etc."""

    payload: dict[str, Any]
    """Raw event data — schema varies by source."""

    timestamp: datetime
    """When the signal was observed. Must be timezone-aware."""

    session_id: str | None = None
    """Agent session identifier, if available."""

    ticket_id: str | None = None
    """Associated ticket ID (e.g. 'OMN-1234'), if available."""

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise ValueError(
                "FrictionSignal.timestamp must be timezone-aware, "
                f"got naive datetime: {self.timestamp!r}"
            )
