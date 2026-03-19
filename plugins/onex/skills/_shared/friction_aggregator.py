# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Friction event aggregation — rolling 30-day window, threshold detection.

Reads the NDJSON registry written by friction_recorder.py and aggregates
events by ``skill:surface`` key. Surfaces crossing either threshold are
candidates for Linear ticket creation via the friction_triage skill.

Thresholds (rolling 30 days):
  - count >= 3  (count-based: recurring nuisance)
  - score >= 9  (score-based: one high or three medium events)

.. versionadded:: OMN-5442
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

THRESHOLD_COUNT = 3
THRESHOLD_SCORE = 9
WINDOW_DAYS = 30

# Import default registry path from friction_recorder to keep single definition.
# Both modules live in the same _shared directory so this import is always available
# when the caller has set up sys.path correctly (e.g. via the skill or test runner).
from friction_recorder import (  # type: ignore[import-not-found]
    _DEFAULT_REGISTRY,
    FrictionSeverity,
)


@dataclass
class FrictionAggregate:
    """Aggregated friction data for a single skill:surface pair."""

    surface_key: str
    skill: str
    surface: str
    count: int = 0
    severity_score: int = 0
    most_recent_ticket: str | None = None
    latest_timestamp: datetime | None = None
    descriptions: list[str] = field(default_factory=list)

    @property
    def threshold_crossed(self) -> bool:
        """True if count >= THRESHOLD_COUNT or severity_score >= THRESHOLD_SCORE."""
        return self.count >= THRESHOLD_COUNT or self.severity_score >= THRESHOLD_SCORE


def aggregate_friction(
    *,
    registry_path: Path | None = None,
    window_days: int = WINDOW_DAYS,
) -> list[FrictionAggregate]:
    """Read the NDJSON registry and aggregate events within the rolling window.

    Args:
        registry_path: Override default registry path (primarily for testing).
        window_days: Rolling window in days (default: 30).

    Returns:
        List of FrictionAggregate objects, one per ``skill:surface`` pair seen
        within the window. Never raises — returns empty list on any I/O error.
    """
    path = Path(registry_path or _DEFAULT_REGISTRY)
    if not path.exists():
        return []

    cutoff = datetime.now(UTC) - timedelta(days=window_days)
    buckets: dict[str, FrictionAggregate] = {}

    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Parse and enforce timezone-awareness
            try:
                ts = datetime.fromisoformat(data.get("timestamp", ""))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
            except (ValueError, TypeError):
                continue

            if ts < cutoff:
                continue

            skill = data.get("skill", "unknown")
            surface = data.get("surface", "unknown")
            key = f"{skill}:{surface}"

            if key not in buckets:
                buckets[key] = FrictionAggregate(
                    surface_key=key, skill=skill, surface=surface
                )

            agg = buckets[key]
            agg.count += 1

            try:
                agg.severity_score += FrictionSeverity(
                    data.get("severity", "low")
                ).weight
            except ValueError:
                agg.severity_score += (
                    1  # fallback: treat unknown severity as low weight
                )

            if agg.latest_timestamp is None or ts > agg.latest_timestamp:
                agg.latest_timestamp = ts
                if data.get("context_ticket_id"):
                    agg.most_recent_ticket = data["context_ticket_id"]

            if data.get("description"):
                agg.descriptions.append(data["description"])

    except Exception as exc:
        logger.debug("friction_aggregator: read failed: %s", exc)

    return list(buckets.values())
