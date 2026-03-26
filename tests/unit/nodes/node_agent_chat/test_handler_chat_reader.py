# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for HandlerChatReader and formatting functions.

Validates:
    - format_message produces correct single-line output
    - Severity prefixes appear for WARN/ERROR/CRITICAL
    - format_messages joins lines correctly
    - read_formatted returns filtered, formatted text
    - read_context_block includes header with count
    - Empty history returns empty string
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from omniclaude.nodes.node_agent_chat import (
    EnumChatChannel,
    EnumChatMessageType,
    EnumChatSeverity,
    HandlerChatReader,
    HandlerFileChatStore,
    ModelAgentChatMessage,
    format_message,
    format_messages,
)


def _make_msg(**overrides: object) -> ModelAgentChatMessage:
    """Factory helper."""
    defaults: dict[str, object] = {
        "emitted_at": datetime(2026, 3, 25, 14, 30, 0, tzinfo=UTC),
        "session_id": "test-session",
        "agent_id": "epic-worker-1",
        "message_type": EnumChatMessageType.STATUS,
        "body": "Started Wave 0",
    }
    defaults.update(overrides)
    return ModelAgentChatMessage(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# format_message tests
# ---------------------------------------------------------------------------


class TestFormatMessage:
    """Tests for format_message()."""

    @pytest.mark.unit
    def test_basic_format(self) -> None:
        msg = _make_msg()
        result = format_message(msg)
        assert result == "[14:30] epic-worker-1 (broadcast): Started Wave 0"

    @pytest.mark.unit
    def test_warn_severity(self) -> None:
        msg = _make_msg(severity=EnumChatSeverity.WARN, body="Low disk space")
        result = format_message(msg)
        assert "[WARN]" in result
        assert "Low disk space" in result

    @pytest.mark.unit
    def test_error_severity(self) -> None:
        msg = _make_msg(severity=EnumChatSeverity.ERROR, body="Build failed")
        result = format_message(msg)
        assert "[ERROR]" in result

    @pytest.mark.unit
    def test_critical_severity(self) -> None:
        msg = _make_msg(severity=EnumChatSeverity.CRITICAL, body="Pipeline halted")
        result = format_message(msg)
        assert "[CRITICAL]" in result

    @pytest.mark.unit
    def test_info_no_prefix(self) -> None:
        msg = _make_msg(severity=EnumChatSeverity.INFO, body="All good")
        result = format_message(msg)
        # No severity prefix for INFO
        assert "[INFO]" not in result
        assert "All good" in result

    @pytest.mark.unit
    def test_ci_channel(self) -> None:
        msg = _make_msg(channel=EnumChatChannel.CI, body="CI alert")
        result = format_message(msg)
        assert "(ci):" in result


class TestFormatMessages:
    """Tests for format_messages()."""

    @pytest.mark.unit
    def test_empty_list(self) -> None:
        assert format_messages([]) == ""

    @pytest.mark.unit
    def test_multiple_messages(self) -> None:
        msgs = [
            _make_msg(body="msg-1"),
            _make_msg(body="msg-2"),
        ]
        result = format_messages(msgs)
        lines = result.strip().splitlines()
        assert len(lines) == 2
        assert "msg-1" in lines[0]
        assert "msg-2" in lines[1]


# ---------------------------------------------------------------------------
# HandlerChatReader tests
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> HandlerFileChatStore:
    """File store backed by tmp dir."""
    return HandlerFileChatStore(path=tmp_path / "chat.jsonl")


@pytest.fixture
def reader(store: HandlerFileChatStore) -> HandlerChatReader:
    """Reader with known store."""
    return HandlerChatReader(store=store)


class TestHandlerChatReader:
    """Tests for HandlerChatReader."""

    @pytest.mark.unit
    def test_read_formatted_empty(self, reader: HandlerChatReader) -> None:
        assert reader.read_formatted() == ""

    @pytest.mark.unit
    def test_read_formatted_with_messages(
        self, reader: HandlerChatReader, store: HandlerFileChatStore
    ) -> None:
        store.append(_make_msg(body="hello"))
        store.append(_make_msg(body="world"))
        result = reader.read_formatted()
        assert "hello" in result
        assert "world" in result
        assert len(result.strip().splitlines()) == 2

    @pytest.mark.unit
    def test_read_formatted_with_channel_filter(
        self, reader: HandlerChatReader, store: HandlerFileChatStore
    ) -> None:
        store.append(_make_msg(channel=EnumChatChannel.BROADCAST, body="broadcast"))
        store.append(_make_msg(channel=EnumChatChannel.CI, body="ci-msg"))
        result = reader.read_formatted(channel="CI")
        assert "ci-msg" in result
        assert "broadcast" not in result

    @pytest.mark.unit
    def test_read_context_block_empty(self, reader: HandlerChatReader) -> None:
        assert reader.read_context_block() == ""

    @pytest.mark.unit
    def test_read_context_block_has_header(
        self, reader: HandlerChatReader, store: HandlerFileChatStore
    ) -> None:
        store.append(_make_msg(body="first"))
        store.append(_make_msg(body="second"))
        result = reader.read_context_block()
        assert result.startswith("## Agent Chat (2 recent messages)")
        assert "first" in result
        assert "second" in result

    @pytest.mark.unit
    def test_read_context_block_count_matches(
        self, reader: HandlerChatReader, store: HandlerFileChatStore
    ) -> None:
        for i in range(7):
            store.append(_make_msg(body=f"msg-{i}"))
        result = reader.read_context_block(n=3)
        assert "3 recent messages" in result
