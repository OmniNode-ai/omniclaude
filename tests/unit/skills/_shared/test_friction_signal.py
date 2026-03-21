# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

_SHARED_PATH = str(
    Path(__file__).resolve().parent.parent.parent.parent.parent
    / "plugins"
    / "onex"
    / "skills"
    / "_shared"
)
if _SHARED_PATH not in sys.path:
    sys.path.insert(0, _SHARED_PATH)

from friction_signal import FrictionSignal


@pytest.mark.unit
class TestFrictionSignal:
    def test_construction(self):
        sig = FrictionSignal(
            source="claude_code_hook",
            event_type="skill.completed",
            payload={"status": "failed", "skill_name": "deploy"},
            timestamp=datetime.now(UTC),
            session_id="sess-123",
        )
        assert sig.source == "claude_code_hook"
        assert sig.event_type == "skill.completed"
        assert sig.payload["status"] == "failed"
        assert sig.session_id == "sess-123"
        assert sig.ticket_id is None

    def test_frozen(self):
        sig = FrictionSignal(
            source="cursor",
            event_type="ci.failed",
            payload={},
            timestamp=datetime.now(UTC),
        )
        with pytest.raises(AttributeError):
            sig.source = "codex"  # type: ignore[misc]

    def test_naive_timestamp_rejected(self):
        with pytest.raises(ValueError, match="timezone-aware"):
            FrictionSignal(
                source="test",
                event_type="test",
                payload={},
                timestamp=datetime(2026, 1, 1),  # naive — no tzinfo
            )

    def test_with_ticket_id(self):
        sig = FrictionSignal(
            source="codex",
            event_type="build.failed",
            payload={"exit_code": 1},
            timestamp=datetime.now(UTC),
            session_id="sess-456",
            ticket_id="OMN-1234",
        )
        assert sig.ticket_id == "OMN-1234"
