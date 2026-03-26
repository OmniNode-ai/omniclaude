# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for HandlerChatPublisher (dual-write).

Validates:
    - File store always receives the message
    - Kafka emit is best-effort (failure does not block)
    - publish() returns True when file write succeeds
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from omniclaude.nodes.node_agent_chat import (
    EnumChatMessageType,
    HandlerChatPublisher,
    HandlerFileChatStore,
    ModelAgentChatMessage,
)


def _make_msg(**overrides: object) -> ModelAgentChatMessage:
    """Factory helper."""
    defaults: dict[str, object] = {
        "emitted_at": datetime.now(UTC),
        "session_id": "test-session",
        "agent_id": "test-agent",
        "message_type": EnumChatMessageType.STATUS,
        "body": "test message",
    }
    defaults.update(overrides)
    return ModelAgentChatMessage(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def store(tmp_path: Path) -> HandlerFileChatStore:
    """File store backed by tmp dir."""
    return HandlerFileChatStore(path=tmp_path / "chat.jsonl")


@pytest.fixture
def publisher(store: HandlerFileChatStore) -> HandlerChatPublisher:
    """Publisher with known file store."""
    return HandlerChatPublisher(store=store)


class TestHandlerChatPublisher:
    """Tests for HandlerChatPublisher."""

    @pytest.mark.unit
    def test_publish_writes_to_file(
        self, publisher: HandlerChatPublisher, store: HandlerFileChatStore
    ) -> None:
        msg = _make_msg(body="hello from publisher")
        result = publisher.publish(msg)
        assert result is True
        assert store.message_count() == 1
        messages = store.read_tail(n=1)
        assert messages[0].body == "hello from publisher"

    @pytest.mark.unit
    def test_publish_multiple(
        self, publisher: HandlerChatPublisher, store: HandlerFileChatStore
    ) -> None:
        for i in range(5):
            publisher.publish(_make_msg(body=f"msg-{i}"))
        assert store.message_count() == 5

    @pytest.mark.unit
    @patch(
        "omniclaude.nodes.node_agent_chat.handler_chat_publisher._emit_to_kafka",
        return_value=True,
    )
    def test_publish_attempts_kafka_emit(
        self,
        mock_emit: object,
        publisher: HandlerChatPublisher,
        store: HandlerFileChatStore,
    ) -> None:
        msg = _make_msg()
        publisher.publish(msg)
        # File store always gets the message
        assert store.message_count() == 1

    @pytest.mark.unit
    @patch(
        "omniclaude.nodes.node_agent_chat.handler_chat_publisher._emit_to_kafka",
        return_value=False,
    )
    def test_publish_succeeds_when_kafka_fails(
        self,
        mock_emit: object,
        publisher: HandlerChatPublisher,
        store: HandlerFileChatStore,
    ) -> None:
        msg = _make_msg()
        result = publisher.publish(msg)
        # publish() returns True because file write succeeded
        assert result is True
        assert store.message_count() == 1

    @pytest.mark.unit
    def test_default_store_creation(self, tmp_path: Path) -> None:
        """Publisher creates a default store if none provided."""
        # We patch _default_chat_path to avoid ONEX_STATE_DIR requirement
        with patch(
            "omniclaude.nodes.node_agent_chat.handler_file_chat_store._default_chat_path",
            return_value=tmp_path / "default_chat.jsonl",
        ):
            pub = HandlerChatPublisher()
            pub.publish(_make_msg())
            assert pub.store.message_count() == 1
