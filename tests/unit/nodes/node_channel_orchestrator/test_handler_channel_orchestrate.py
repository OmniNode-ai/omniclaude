# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for channel orchestration handler."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from omnibase_core.enums.enum_channel_type import EnumChannelType
from omnibase_core.models.channel.model_channel_envelope import ModelChannelEnvelope

from omniclaude.nodes.node_channel_orchestrator.handlers.handler_channel_orchestrate import (
    handle_channel_orchestrate,
)
from omniclaude.nodes.node_channel_orchestrator.models.model_channel_orchestrator_output import (
    ModelChannelOrchestratorOutput,
)


def _make_envelope(**overrides: object) -> ModelChannelEnvelope:
    defaults: dict[str, object] = {
        "channel_id": "general",
        "channel_type": EnumChannelType.DISCORD,
        "sender_id": "user-123",
        "message_text": "What is ONEX?",
        "message_id": "msg-456",
        "timestamp": datetime.now(tz=UTC),
        "correlation_id": uuid4(),
    }
    defaults.update(overrides)
    return ModelChannelEnvelope(**defaults)  # type: ignore[arg-type]


@pytest.mark.unit
class TestHandlerChannelOrchestrate:
    """Test cases for handle_channel_orchestrate."""

    def test_returns_output_model(self) -> None:
        envelope = _make_envelope()
        result = handle_channel_orchestrate(envelope)
        assert isinstance(result, ModelChannelOrchestratorOutput)

    def test_reply_text_populated(self) -> None:
        envelope = _make_envelope(message_text="hello")
        result = handle_channel_orchestrate(envelope)
        assert result.reply_text
        assert "hello" in result.reply_text

    def test_preserves_channel_routing(self) -> None:
        envelope = _make_envelope(
            channel_type=EnumChannelType.SLACK,
            channel_id="C12345",
        )
        result = handle_channel_orchestrate(envelope)
        assert result.channel_type == EnumChannelType.SLACK
        assert result.channel_id == "C12345"

    def test_preserves_correlation_id(self) -> None:
        cid = uuid4()
        envelope = _make_envelope(correlation_id=cid)
        result = handle_channel_orchestrate(envelope)
        assert result.correlation_id == cid

    def test_sets_reply_to_message_id(self) -> None:
        envelope = _make_envelope(message_id="msg-789")
        result = handle_channel_orchestrate(envelope)
        assert result.reply_to == "msg-789"

    def test_preserves_thread_id(self) -> None:
        envelope = _make_envelope(thread_id="thread-42")
        result = handle_channel_orchestrate(envelope)
        assert result.thread_id == "thread-42"

    def test_all_channel_types(self) -> None:
        for ct in EnumChannelType:
            envelope = _make_envelope(channel_type=ct)
            result = handle_channel_orchestrate(envelope)
            assert result.channel_type == ct
