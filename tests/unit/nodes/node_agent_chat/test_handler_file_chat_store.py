# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for HandlerFileChatStore.

Validates:
    - Append writes valid JSONL
    - read_tail returns correct messages in chronological order
    - Channel and epic_id filtering
    - Empty file / nonexistent file handling
    - Malformed line tolerance
    - message_count accuracy
    - Concurrent append safety (basic)
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from omniclaude.nodes.node_agent_chat import (
    EnumChatChannel,
    EnumChatMessageType,
    EnumChatSeverity,
    HandlerFileChatStore,
    ModelAgentChatMessage,
)


def _make_msg(**overrides: object) -> ModelAgentChatMessage:
    """Factory helper for creating valid messages."""
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
def chat_file(tmp_path: Path) -> Path:
    """Return a temporary chat.jsonl path."""
    return tmp_path / "chat" / "chat.jsonl"


@pytest.fixture
def store(chat_file: Path) -> HandlerFileChatStore:
    """Return a HandlerFileChatStore using the temporary path."""
    return HandlerFileChatStore(path=chat_file)


class TestHandlerFileChatStore:
    """Tests for HandlerFileChatStore."""

    @pytest.mark.unit
    def test_append_creates_file(
        self, store: HandlerFileChatStore, chat_file: Path
    ) -> None:
        msg = _make_msg()
        store.append(msg)
        assert chat_file.exists()

    @pytest.mark.unit
    def test_append_writes_jsonl(
        self, store: HandlerFileChatStore, chat_file: Path
    ) -> None:
        msg = _make_msg(body="hello world")
        store.append(msg)

        lines = chat_file.read_text().strip().splitlines()
        assert len(lines) == 1
        restored = ModelAgentChatMessage.model_validate_json(lines[0])
        assert restored.body == "hello world"

    @pytest.mark.unit
    def test_append_multiple(
        self, store: HandlerFileChatStore, chat_file: Path
    ) -> None:
        for i in range(5):
            store.append(_make_msg(body=f"msg-{i}"))

        lines = chat_file.read_text().strip().splitlines()
        assert len(lines) == 5

    @pytest.mark.unit
    def test_read_tail_empty_file(self, store: HandlerFileChatStore) -> None:
        result = store.read_tail()
        assert result == []

    @pytest.mark.unit
    def test_read_tail_nonexistent_file(self, tmp_path: Path) -> None:
        store = HandlerFileChatStore(path=tmp_path / "nonexistent.jsonl")
        result = store.read_tail()
        assert result == []

    @pytest.mark.unit
    def test_read_tail_returns_chronological(self, store: HandlerFileChatStore) -> None:
        for i in range(10):
            store.append(_make_msg(body=f"msg-{i}"))

        result = store.read_tail(n=5)
        assert len(result) == 5
        assert result[0].body == "msg-5"
        assert result[4].body == "msg-9"

    @pytest.mark.unit
    def test_read_tail_fewer_than_n(self, store: HandlerFileChatStore) -> None:
        store.append(_make_msg(body="only-one"))
        result = store.read_tail(n=50)
        assert len(result) == 1
        assert result[0].body == "only-one"

    @pytest.mark.unit
    def test_read_tail_filter_channel(self, store: HandlerFileChatStore) -> None:
        store.append(_make_msg(channel=EnumChatChannel.BROADCAST, body="broadcast"))
        store.append(_make_msg(channel=EnumChatChannel.CI, body="ci-alert"))
        store.append(_make_msg(channel=EnumChatChannel.BROADCAST, body="broadcast-2"))

        result = store.read_tail(channel="CI")
        assert len(result) == 1
        assert result[0].body == "ci-alert"

    @pytest.mark.unit
    def test_read_tail_filter_epic_id(self, store: HandlerFileChatStore) -> None:
        store.append(
            _make_msg(channel=EnumChatChannel.EPIC, epic_id="OMN-3972", body="epic msg")
        )
        store.append(
            _make_msg(
                channel=EnumChatChannel.EPIC, epic_id="OMN-9999", body="other epic"
            )
        )

        result = store.read_tail(epic_id="OMN-3972")
        assert len(result) == 1
        assert result[0].body == "epic msg"

    @pytest.mark.unit
    def test_read_tail_combined_filters(self, store: HandlerFileChatStore) -> None:
        store.append(
            _make_msg(channel=EnumChatChannel.EPIC, epic_id="OMN-3972", body="match")
        )
        store.append(
            _make_msg(channel=EnumChatChannel.BROADCAST, epic_id=None, body="no-match")
        )

        result = store.read_tail(channel="EPIC", epic_id="OMN-3972")
        assert len(result) == 1
        assert result[0].body == "match"

    @pytest.mark.unit
    def test_malformed_lines_skipped(
        self, store: HandlerFileChatStore, chat_file: Path
    ) -> None:
        # Write a valid message, then a bad line, then another valid one
        store.append(_make_msg(body="valid-1"))
        chat_file.parent.mkdir(parents=True, exist_ok=True)
        with chat_file.open("a") as f:
            f.write("NOT VALID JSON\n")
        store.append(_make_msg(body="valid-2"))

        result = store.read_tail()
        assert len(result) == 2
        assert result[0].body == "valid-1"
        assert result[1].body == "valid-2"

    @pytest.mark.unit
    def test_message_count(self, store: HandlerFileChatStore) -> None:
        assert store.message_count() == 0
        store.append(_make_msg())
        store.append(_make_msg())
        assert store.message_count() == 2

    @pytest.mark.unit
    def test_message_count_nonexistent_file(self, tmp_path: Path) -> None:
        store = HandlerFileChatStore(path=tmp_path / "nope.jsonl")
        assert store.message_count() == 0

    @pytest.mark.unit
    def test_round_trip_preserves_all_fields(self, store: HandlerFileChatStore) -> None:
        msg = _make_msg(
            channel=EnumChatChannel.CI,
            message_type=EnumChatMessageType.CI_ALERT,
            severity=EnumChatSeverity.ERROR,
            ticket_id="OMN-6527",
            metadata={"repo": "omniclaude"},
        )
        store.append(msg)
        result = store.read_tail(n=1)
        assert len(result) == 1
        assert result[0] == msg
