# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for friction_recorder.py.

Tests cover:
- compute_surface_key format
- FrictionSeverity weights
- normalize_surface_category — valid and unknown categories
- record_friction — NDJSON append (single and multiple)
- Naive timestamp rejection
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
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

from friction_recorder import (
    SURFACE_CATEGORY_ALLOWLIST,
    FrictionEvent,
    FrictionSeverity,
    compute_surface_key,
    normalize_surface_category,
    record_friction,
)

pytestmark = pytest.mark.unit


def test_surface_key_format() -> None:
    assert (
        compute_surface_key("integration_sweep", "kafka/missing-topic")
        == "integration_sweep:kafka/missing-topic"
    )


def test_severity_weights() -> None:
    assert FrictionSeverity.LOW.weight == 1
    assert FrictionSeverity.MEDIUM.weight == 3
    assert FrictionSeverity.HIGH.weight == 9


def test_normalize_surface_category_unknown() -> None:
    result = normalize_surface_category("mycat/something")
    assert result == "unknown/mycat-something"


def test_normalize_surface_category_valid() -> None:
    assert normalize_surface_category("kafka/missing-topic") == "kafka/missing-topic"


def test_surface_category_allowlist_completeness() -> None:
    expected = {"kafka", "ci", "config", "permissions", "linear", "network", "auth", "tooling", "unknown"}
    assert SURFACE_CATEGORY_ALLOWLIST == expected


def test_record_appends_ndjson(tmp_path: Path) -> None:
    registry = tmp_path / "friction.ndjson"
    event = FrictionEvent(
        skill="integration_sweep",
        surface="kafka/missing-topic",
        severity=FrictionSeverity.MEDIUM,
        description="Topic not found",
        context_ticket_id="OMN-5132",
        session_id="test-session",
        timestamp=datetime.now(UTC),
    )
    record_friction(event, registry_path=registry, emit_kafka=False)
    data = json.loads(registry.read_text().strip())
    assert data["skill"] == "integration_sweep"
    assert data["severity"] == "medium"
    assert data["surface"] == "kafka/missing-topic"


def test_record_appends_multiple(tmp_path: Path) -> None:
    registry = tmp_path / "friction.ndjson"
    for _ in range(3):
        event = FrictionEvent(
            skill="gap",
            surface="ci/missing-workflow",
            severity=FrictionSeverity.LOW,
            description="",
            context_ticket_id=None,
            session_id="s",
            timestamp=datetime.now(UTC),
        )
        record_friction(event, registry_path=registry, emit_kafka=False)
    assert len(registry.read_text().strip().splitlines()) == 3


def test_naive_timestamp_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        FrictionEvent(
            skill="x",
            surface="kafka/test",
            severity=FrictionSeverity.LOW,
            description="",
            context_ticket_id=None,
            session_id="s",
            timestamp=datetime(2026, 1, 1),  # naive — no tzinfo
        )


def test_record_creates_parent_dirs(tmp_path: Path) -> None:
    registry = tmp_path / "nested" / "dir" / "friction.ndjson"
    event = FrictionEvent(
        skill="gap",
        surface="ci/missing-workflow",
        severity=FrictionSeverity.LOW,
        description="test",
        context_ticket_id=None,
        session_id="s",
        timestamp=datetime.now(UTC),
    )
    record_friction(event, registry_path=registry, emit_kafka=False)
    assert registry.exists()
