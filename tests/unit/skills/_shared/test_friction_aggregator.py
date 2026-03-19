# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for friction_aggregator.py.

Tests cover:
- Below count threshold — no crossing
- Crosses count threshold (count >= 3)
- Crosses score threshold on single high-severity event (score >= 9)
- Ignores events outside the rolling window
- Skips malformed NDJSON lines silently
- Empty registry returns empty list
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

# _shared path injection for direct test invocation
_SHARED_PATH = str(
    Path(__file__).parent.parent.parent.parent.parent
    / "plugins"
    / "onex"
    / "skills"
    / "_shared"
)
if _SHARED_PATH not in sys.path:
    sys.path.insert(0, _SHARED_PATH)

from friction_aggregator import (
    THRESHOLD_COUNT,
    THRESHOLD_SCORE,
    WINDOW_DAYS,
    FrictionAggregate,
    aggregate_friction,
)

pytestmark = pytest.mark.unit


def _write_events(
    tmp_path: Path,
    *,
    count: int,
    severity: str,
    skill: str = "gap",
    surface: str = "ci/missing-workflow",
    timestamp: datetime | None = None,
) -> Path:
    registry = tmp_path / "friction.ndjson"
    ts = timestamp or datetime.now(UTC)
    with registry.open("a", encoding="utf-8") as f:
        for _ in range(count):
            f.write(
                json.dumps(
                    {
                        "skill": skill,
                        "surface": surface,
                        "severity": severity,
                        "description": "test",
                        "context_ticket_id": None,
                        "session_id": "s",
                        "timestamp": ts.isoformat(),
                    }
                )
                + "\n"
            )
    return registry


def test_below_count_threshold(tmp_path: Path) -> None:
    registry = _write_events(tmp_path, count=2, severity="low")
    aggregates = aggregate_friction(registry_path=registry)
    assert all(not a.threshold_crossed for a in aggregates)


def test_crosses_count_threshold(tmp_path: Path) -> None:
    registry = _write_events(tmp_path, count=3, severity="low")
    aggregates = aggregate_friction(registry_path=registry)
    crossed = [a for a in aggregates if a.threshold_crossed]
    assert len(crossed) == 1
    assert crossed[0].surface_key == "gap:ci/missing-workflow"


def test_crosses_score_threshold_on_single_high(tmp_path: Path) -> None:
    registry = _write_events(tmp_path, count=1, severity="high")
    aggregates = aggregate_friction(registry_path=registry)
    crossed = [a for a in aggregates if a.threshold_crossed]
    assert len(crossed) == 1
    assert crossed[0].severity_score == 9


def test_ignores_events_outside_window(tmp_path: Path) -> None:
    old = datetime.now(UTC) - timedelta(days=31)
    registry = _write_events(tmp_path, count=5, severity="low", timestamp=old)
    aggregates = aggregate_friction(registry_path=registry)
    assert all(not a.threshold_crossed for a in aggregates)


def test_skips_malformed_lines(tmp_path: Path) -> None:
    registry = tmp_path / "friction.ndjson"
    with registry.open("w", encoding="utf-8") as f:
        # Malformed line
        f.write("not json\n")
        # Valid line
        f.write(
            json.dumps(
                {
                    "skill": "x",
                    "surface": "kafka/t",
                    "severity": "low",
                    "description": "",
                    "context_ticket_id": None,
                    "session_id": "s",
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
            + "\n"
        )
    aggregates = aggregate_friction(registry_path=registry)
    assert isinstance(aggregates, list)
    assert len(aggregates) == 1


def test_empty_registry_returns_empty(tmp_path: Path) -> None:
    registry = tmp_path / "friction.ndjson"
    registry.write_text("")
    aggregates = aggregate_friction(registry_path=registry)
    assert aggregates == []


def test_missing_registry_returns_empty(tmp_path: Path) -> None:
    registry = tmp_path / "nonexistent.ndjson"
    aggregates = aggregate_friction(registry_path=registry)
    assert aggregates == []


def test_multiple_surfaces_tracked_independently(tmp_path: Path) -> None:
    registry = _write_events(
        tmp_path, count=3, severity="low", skill="gap", surface="ci/missing-workflow"
    )
    _write_events(
        tmp_path,
        count=1,
        severity="high",
        skill="pr_polish",
        surface="linear/api-timeout",
    )
    # Reuse same file by passing it via registry_path (already written above)
    aggregates = aggregate_friction(registry_path=registry)
    assert len(aggregates) == 2
    crossed = [a for a in aggregates if a.threshold_crossed]
    assert len(crossed) == 2


def test_threshold_constants() -> None:
    assert THRESHOLD_COUNT == 3
    assert THRESHOLD_SCORE == 9
    assert WINDOW_DAYS == 30
