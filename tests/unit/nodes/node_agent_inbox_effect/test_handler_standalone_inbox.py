# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Tests for HandlerStandaloneInbox - file-based agent inbox delivery."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from omniclaude.nodes.node_agent_inbox_effect.handler_standalone_inbox import (
    HandlerStandaloneInbox,
)
from omniclaude.nodes.node_agent_inbox_effect.models import (
    ModelInboxMessage,
    ModelMessageTrace,
)


def _make_trace() -> ModelMessageTrace:
    """Create a test trace context."""
    return ModelMessageTrace(
        correlation_id=uuid4(),
        run_id="test-run-001",
    )


def _make_directed_message(
    target_agent_id: str = "worker-omniclaude",
    msg_type: str = "agent.task.completed",
) -> ModelInboxMessage:
    """Create a directed test message."""
    return ModelInboxMessage(
        message_id=uuid4(),
        emitted_at=datetime.now(UTC),
        trace=_make_trace(),
        type=msg_type,  # type: ignore[arg-type]
        source_agent_id="worker-omnibase-core",
        target_agent_id=target_agent_id,
        payload={
            "pr_url": "https://github.com/org/repo/pull/1",
            "commit_sha": "abc123",
        },
    )


def _make_broadcast_message(
    target_epic_id: str = "OMN-2821",
) -> ModelInboxMessage:
    """Create a broadcast test message."""
    return ModelInboxMessage(
        message_id=uuid4(),
        emitted_at=datetime.now(UTC),
        trace=_make_trace(),
        type="agent.task.completed",
        source_agent_id="worker-omniclaude",
        target_epic_id=target_epic_id,
        payload={"ticket_id": "OMN-2827", "status": "completed"},
    )


@pytest.mark.unit
class TestHandlerStandaloneInbox:
    """Test suite for standalone file-based inbox handler."""

    @pytest.mark.asyncio
    async def test_send_directed_message(self, tmp_path: Path) -> None:
        """Directed message creates file in agent-specific directory."""
        handler = HandlerStandaloneInbox(inbox_root=str(tmp_path))
        message = _make_directed_message()

        result = await handler.send_message(message)

        assert result.success is True
        assert result.standalone_delivered is True
        assert result.kafka_delivered is False
        assert result.delivery_tier == "standalone"
        assert result.file_path is not None

        # Verify file exists and is valid JSON
        file_path = Path(result.file_path)
        assert file_path.exists()
        data = json.loads(file_path.read_text())
        assert data["message_id"] == str(message.message_id)
        assert data["type"] == "agent.task.completed"
        assert data["target_agent_id"] == "worker-omniclaude"

    @pytest.mark.asyncio
    async def test_send_broadcast_message(self, tmp_path: Path) -> None:
        """Broadcast message creates file in _broadcast/{epic_id}/ directory."""
        handler = HandlerStandaloneInbox(inbox_root=str(tmp_path))
        message = _make_broadcast_message()

        result = await handler.send_message(message)

        assert result.success is True
        assert result.standalone_delivered is True
        assert result.file_path is not None

        # Verify directory structure
        file_path = Path(result.file_path)
        assert file_path.exists()
        assert "_broadcast" in str(file_path)
        assert "OMN-2821" in str(file_path)

    @pytest.mark.asyncio
    async def test_receive_messages_empty_inbox(self, tmp_path: Path) -> None:
        """Receive from non-existent inbox returns empty list."""
        handler = HandlerStandaloneInbox(inbox_root=str(tmp_path))

        messages = await handler.receive_messages("nonexistent-agent")

        assert messages == []

    @pytest.mark.asyncio
    async def test_receive_messages_returns_sent(self, tmp_path: Path) -> None:
        """Messages sent to an agent can be received back in order."""
        handler = HandlerStandaloneInbox(inbox_root=str(tmp_path))

        # Send 3 messages
        sent = []
        for _ in range(3):
            msg = _make_directed_message()
            await handler.send_message(msg)
            sent.append(msg)

        # Receive
        received = await handler.receive_messages("worker-omniclaude")

        assert len(received) == 3
        # Verify order (oldest first)
        for i in range(len(received) - 1):
            assert received[i].emitted_at <= received[i + 1].emitted_at

    @pytest.mark.asyncio
    async def test_receive_messages_since_filter(self, tmp_path: Path) -> None:
        """Messages can be filtered by 'since' timestamp."""
        handler = HandlerStandaloneInbox(inbox_root=str(tmp_path))

        msg1 = _make_directed_message()
        await handler.send_message(msg1)

        cutoff = datetime.now(UTC)

        msg2 = _make_directed_message()
        await handler.send_message(msg2)

        # Receive only messages after cutoff
        received = await handler.receive_messages("worker-omniclaude", since=cutoff)

        assert len(received) == 1
        assert received[0].message_id == msg2.message_id

    @pytest.mark.asyncio
    async def test_gc_inbox_removes_old_files(self, tmp_path: Path) -> None:
        """GC removes files older than TTL."""
        handler = HandlerStandaloneInbox(inbox_root=str(tmp_path))

        msg = _make_directed_message()
        result = await handler.send_message(msg)
        assert result.file_path is not None

        # Make the file appear old by backdating mtime
        import os
        import time

        old_time = time.time() - (25 * 3600)  # 25 hours ago
        os.utime(result.file_path, (old_time, old_time))

        removed = await handler.gc_inbox(ttl_hours=24)

        assert removed == 1
        assert not Path(result.file_path).exists()

    @pytest.mark.asyncio
    async def test_gc_inbox_preserves_recent_files(self, tmp_path: Path) -> None:
        """GC preserves files newer than TTL."""
        handler = HandlerStandaloneInbox(inbox_root=str(tmp_path))

        msg = _make_directed_message()
        result = await handler.send_message(msg)
        assert result.file_path is not None

        removed = await handler.gc_inbox(ttl_hours=24)

        assert removed == 0
        assert Path(result.file_path).exists()

    @pytest.mark.asyncio
    async def test_atomic_write_no_partial_reads(self, tmp_path: Path) -> None:
        """Verify no .tmp files remain after successful write."""
        handler = HandlerStandaloneInbox(inbox_root=str(tmp_path))
        message = _make_directed_message()

        await handler.send_message(message)

        # Check no .tmp files exist
        agent_dir = tmp_path / "worker-omniclaude"
        tmp_files = list(agent_dir.glob("*.tmp"))
        assert len(tmp_files) == 0

        # Only .json files exist
        json_files = list(agent_dir.glob("*.json"))
        assert len(json_files) == 1


@pytest.mark.unit
class TestModelInboxMessage:
    """Test suite for the ModelInboxMessage envelope."""

    def test_requires_timezone_aware_timestamp(self) -> None:
        """Naive datetimes are rejected."""
        with pytest.raises(ValueError, match="timezone-aware"):
            ModelInboxMessage(
                message_id=uuid4(),
                emitted_at=datetime(2026, 1, 1, 0, 0, 0),  # naive
                trace=_make_trace(),
                type="agent.task.completed",
                source_agent_id="worker-a",
                target_agent_id="worker-b",
            )

    def test_requires_exactly_one_target(self) -> None:
        """Must set exactly one of target_agent_id or target_epic_id."""
        # Neither set
        with pytest.raises(ValueError, match="Exactly one"):
            ModelInboxMessage(
                message_id=uuid4(),
                emitted_at=datetime.now(UTC),
                trace=_make_trace(),
                type="agent.task.completed",
                source_agent_id="worker-a",
            )

        # Both set
        with pytest.raises(ValueError, match="Cannot set both"):
            ModelInboxMessage(
                message_id=uuid4(),
                emitted_at=datetime.now(UTC),
                trace=_make_trace(),
                type="agent.task.completed",
                source_agent_id="worker-a",
                target_agent_id="worker-b",
                target_epic_id="OMN-1234",
            )

    def test_valid_directed_message(self) -> None:
        """Valid directed message passes validation."""
        msg = _make_directed_message()
        assert msg.target_agent_id == "worker-omniclaude"
        assert msg.target_epic_id is None

    def test_valid_broadcast_message(self) -> None:
        """Valid broadcast message passes validation."""
        msg = _make_broadcast_message()
        assert msg.target_epic_id == "OMN-2821"
        assert msg.target_agent_id is None

    def test_message_is_frozen(self) -> None:
        """Messages are immutable."""
        msg = _make_directed_message()
        with pytest.raises(Exception):  # noqa: B017
            msg.type = "agent.unblock"  # type: ignore[misc]
