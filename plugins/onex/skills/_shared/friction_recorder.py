# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Friction event recording — shared utility for all omniclaude skills.

Registry contract:
  - Append-only NDJSON at ~/.claude/state/friction/friction.ndjson
  - Malformed lines are skipped by readers
  - No rotation in Phase 1
  - Kafka emission is opportunistic side-channel; failures are swallowed

Surface taxonomy: <category>/<specific>
  Allowed categories: kafka, ci, config, permissions, linear, network, auth, tooling, unknown
  Unknown categories normalized to: unknown/<original-mangled>

Severity weights: low=1, medium=3, high=9
Threshold: count >= 3 OR severity_score >= 9 (rolling 30 days)

.. versionadded:: OMN-5442
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_REGISTRY = Path(
    os.environ.get(
        "FRICTION_REGISTRY_PATH",
        str(Path.home() / ".claude" / "state" / "friction" / "friction.ndjson"),
    )
)

SURFACE_CATEGORY_ALLOWLIST = frozenset(
    {
        "kafka",
        "ci",
        "config",
        "permissions",
        "linear",
        "network",
        "auth",
        "tooling",
        "unknown",
    }
)


class FrictionSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @property
    def weight(self) -> int:
        return {"low": 1, "medium": 3, "high": 9}[self.value]


def normalize_surface_category(surface: str) -> str:
    """Normalize surface to allowed category. Unknown categories → unknown/<mangled>."""
    parts = surface.split("/", 1)
    category = parts[0].lower()
    specific = parts[1] if len(parts) > 1 else "unspecified"
    if category in SURFACE_CATEGORY_ALLOWLIST:
        return f"{category}/{specific}"
    mangled = re.sub(r"[^a-z0-9-]", "-", f"{category}-{specific}")
    return f"unknown/{mangled}"


def compute_surface_key(skill: str, surface: str) -> str:
    """Return the canonical dedup key for a skill+surface pair."""
    return f"{skill}:{normalize_surface_category(surface)}"


class FrictionEvent:
    """A single friction occurrence recorded by a skill."""

    def __init__(
        self,
        *,
        skill: str,
        surface: str,
        severity: FrictionSeverity,
        description: str,
        context_ticket_id: str | None,
        session_id: str,
        timestamp: datetime,
    ) -> None:
        if timestamp.tzinfo is None:
            raise ValueError(
                "timestamp must be timezone-aware (e.g. datetime.now(UTC))"
            )
        self.skill = skill
        self.surface = normalize_surface_category(surface)
        self.severity = severity
        self.description = description
        self.context_ticket_id = context_ticket_id
        self.session_id = session_id
        self.timestamp = timestamp

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill": self.skill,
            "surface": self.surface,
            "severity": self.severity.value,
            "description": self.description,
            "context_ticket_id": self.context_ticket_id,
            "session_id": self.session_id,
            "timestamp": self.timestamp.isoformat(),
        }


def record_friction(
    event: FrictionEvent,
    *,
    registry_path: Path | None = None,
    emit_kafka: bool = True,
) -> None:
    """Append friction event to NDJSON registry. Non-blocking; never raises."""
    path = Path(registry_path or _DEFAULT_REGISTRY)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event.to_dict()) + "\n")
    except Exception as exc:
        logger.debug("friction_recorder: append failed: %s", exc)

    if emit_kafka:
        _emit_kafka(event)


def _emit_kafka(event: FrictionEvent) -> None:
    """Opportunistic side-channel Kafka emission. Failures are always swallowed."""
    try:
        # Lazy import to avoid hard dependency on hook lib from skills
        import sys as _sys

        _lib_path = str(Path(__file__).parent.parent.parent / "hooks" / "lib")
        if _lib_path not in _sys.path:
            _sys.path.insert(0, _lib_path)
        from emit_client_wrapper import emit_event

        emit_event("skill.friction-recorded", event.to_dict())
    except Exception as exc:
        logger.debug("friction_recorder: kafka emit failed: %s", exc)
