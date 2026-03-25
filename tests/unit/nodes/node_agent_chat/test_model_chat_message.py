# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for ModelAgentChatMessage and chat enums.

Validates:
    - All enum members exist and are str enums
    - ModelAgentChatMessage construction with required/optional fields
    - Frozen immutability
    - Timezone-aware datetime enforcement
    - Field validation (min_length, max_length)
    - JSON round-trip serialization
    - Default values
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from omniclaude.nodes.node_agent_chat import (
    EnumChatChannel,
    EnumChatMessageType,
    EnumChatSeverity,
    ModelAgentChatMessage,
)

# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


class TestEnumChatChannel:
    """Tests for EnumChatChannel."""

    @pytest.mark.unit
    def test_members_exist(self) -> None:
        assert EnumChatChannel.BROADCAST == "BROADCAST"
        assert EnumChatChannel.EPIC == "EPIC"
        assert EnumChatChannel.CI == "CI"
        assert EnumChatChannel.SYSTEM == "SYSTEM"

    @pytest.mark.unit
    def test_is_str_enum(self) -> None:
        assert isinstance(EnumChatChannel.BROADCAST, str)

    @pytest.mark.unit
    def test_member_count(self) -> None:
        assert len(EnumChatChannel) == 4


class TestEnumChatMessageType:
    """Tests for EnumChatMessageType."""

    @pytest.mark.unit
    def test_members_exist(self) -> None:
        assert EnumChatMessageType.STATUS == "STATUS"
        assert EnumChatMessageType.PROGRESS == "PROGRESS"
        assert EnumChatMessageType.CI_ALERT == "CI_ALERT"
        assert EnumChatMessageType.COORDINATION == "COORDINATION"
        assert EnumChatMessageType.HUMAN == "HUMAN"
        assert EnumChatMessageType.SYSTEM == "SYSTEM"

    @pytest.mark.unit
    def test_is_str_enum(self) -> None:
        assert isinstance(EnumChatMessageType.STATUS, str)

    @pytest.mark.unit
    def test_member_count(self) -> None:
        assert len(EnumChatMessageType) == 6


class TestEnumChatSeverity:
    """Tests for EnumChatSeverity."""

    @pytest.mark.unit
    def test_members_exist(self) -> None:
        assert EnumChatSeverity.INFO == "INFO"
        assert EnumChatSeverity.WARN == "WARN"
        assert EnumChatSeverity.ERROR == "ERROR"
        assert EnumChatSeverity.CRITICAL == "CRITICAL"

    @pytest.mark.unit
    def test_is_str_enum(self) -> None:
        assert isinstance(EnumChatSeverity.INFO, str)

    @pytest.mark.unit
    def test_member_count(self) -> None:
        assert len(EnumChatSeverity) == 4


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


def _make_msg(**overrides: object) -> ModelAgentChatMessage:
    """Factory helper for creating valid ModelAgentChatMessage instances."""
    defaults: dict[str, object] = {
        "emitted_at": datetime.now(UTC),
        "session_id": "test-session-001",
        "agent_id": "epic-worker-1",
        "message_type": EnumChatMessageType.STATUS,
        "body": "Worker started on Wave 0",
    }
    defaults.update(overrides)
    return ModelAgentChatMessage(**defaults)  # type: ignore[arg-type]


class TestModelAgentChatMessage:
    """Tests for ModelAgentChatMessage."""

    @pytest.mark.unit
    def test_minimal_construction(self) -> None:
        msg = _make_msg()
        assert msg.session_id == "test-session-001"
        assert msg.agent_id == "epic-worker-1"
        assert msg.message_type == EnumChatMessageType.STATUS
        assert msg.body == "Worker started on Wave 0"

    @pytest.mark.unit
    def test_defaults(self) -> None:
        msg = _make_msg()
        assert msg.schema_version == "1"
        assert msg.channel == EnumChatChannel.BROADCAST
        assert msg.severity == EnumChatSeverity.INFO
        assert msg.epic_id is None
        assert msg.correlation_id is None
        assert msg.ticket_id is None
        assert msg.metadata == {}

    @pytest.mark.unit
    def test_message_id_auto_generated(self) -> None:
        msg = _make_msg()
        assert isinstance(msg.message_id, UUID)

    @pytest.mark.unit
    def test_message_id_explicit(self) -> None:
        explicit_id = uuid4()
        msg = _make_msg(message_id=explicit_id)
        assert msg.message_id == explicit_id

    @pytest.mark.unit
    def test_full_construction(self) -> None:
        cid = uuid4()
        msg = _make_msg(
            channel=EnumChatChannel.EPIC,
            severity=EnumChatSeverity.WARN,
            epic_id="OMN-3972",
            correlation_id=cid,
            ticket_id="OMN-6507",
            metadata={"wave": "0", "ticket_count": "10"},
        )
        assert msg.channel == EnumChatChannel.EPIC
        assert msg.severity == EnumChatSeverity.WARN
        assert msg.epic_id == "OMN-3972"
        assert msg.correlation_id == cid
        assert msg.ticket_id == "OMN-6507"
        assert msg.metadata == {"wave": "0", "ticket_count": "10"}

    @pytest.mark.unit
    def test_frozen_immutability(self) -> None:
        msg = _make_msg()
        with pytest.raises(Exception):  # ValidationError for frozen model
            msg.body = "modified"  # type: ignore[misc]

    @pytest.mark.unit
    def test_extra_fields_ignored(self) -> None:
        """Extra fields are silently ignored (extra='ignore' in ConfigDict)."""
        msg = _make_msg(unknown_field="bad")
        assert not hasattr(msg, "unknown_field")

    @pytest.mark.unit
    def test_naive_datetime_rejected(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            _make_msg(emitted_at=datetime(2026, 3, 25, 12, 0, 0))  # noqa: DTZ001

    @pytest.mark.unit
    def test_empty_session_id_rejected(self) -> None:
        with pytest.raises(Exception):
            _make_msg(session_id="")

    @pytest.mark.unit
    def test_empty_agent_id_rejected(self) -> None:
        with pytest.raises(Exception):
            _make_msg(agent_id="")

    @pytest.mark.unit
    def test_empty_body_rejected(self) -> None:
        with pytest.raises(Exception):
            _make_msg(body="")

    @pytest.mark.unit
    def test_body_max_length(self) -> None:
        with pytest.raises(Exception):
            _make_msg(body="x" * 4097)

    @pytest.mark.unit
    def test_body_at_max_length(self) -> None:
        msg = _make_msg(body="x" * 4096)
        assert len(msg.body) == 4096

    @pytest.mark.unit
    def test_json_round_trip(self) -> None:
        msg = _make_msg(
            channel=EnumChatChannel.CI,
            message_type=EnumChatMessageType.CI_ALERT,
            severity=EnumChatSeverity.ERROR,
            ticket_id="OMN-6527",
        )
        json_str = msg.model_dump_json()
        restored = ModelAgentChatMessage.model_validate_json(json_str)
        assert restored == msg

    @pytest.mark.unit
    def test_dict_round_trip(self) -> None:
        msg = _make_msg()
        data = msg.model_dump()
        restored = ModelAgentChatMessage.model_validate(data)
        assert restored == msg

    @pytest.mark.unit
    def test_from_attributes(self) -> None:
        """Verify from_attributes=True in ConfigDict works."""
        msg = _make_msg()
        # model_validate with from_attributes uses attribute access
        restored = ModelAgentChatMessage.model_validate(msg, from_attributes=True)
        assert restored == msg
