# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Integration test for the agent chat pipeline.

Validates the full path: publish -> file store -> reader, ensuring all
components work together without mocking.

Also tests the auto-emit convenience functions.

Related tickets:
    - OMN-3972: Agentic Chat Over Kafka MVP
    - OMN-6530: Integration test
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from omniclaude.nodes.node_agent_chat import (
    EnumChatChannel,
    EnumChatMessageType,
    EnumChatSeverity,
    HandlerChatPublisher,
    HandlerChatReader,
    HandlerFileChatStore,
    ModelAgentChatMessage,
    emit_ci_alert,
    emit_progress,
    emit_status,
)


@pytest.fixture
def chat_file(tmp_path: Path) -> Path:
    """Temporary chat file."""
    return tmp_path / "chat" / "chat.jsonl"


@pytest.fixture
def store(chat_file: Path) -> HandlerFileChatStore:
    """File store backed by tmp dir."""
    return HandlerFileChatStore(path=chat_file)


@pytest.fixture
def publisher(store: HandlerFileChatStore) -> HandlerChatPublisher:
    """Publisher with known store."""
    return HandlerChatPublisher(store=store)


@pytest.fixture
def reader(store: HandlerFileChatStore) -> HandlerChatReader:
    """Reader with known store."""
    return HandlerChatReader(store=store)


class TestChatPipelineIntegration:
    """End-to-end tests for publish -> store -> read pipeline."""

    @pytest.mark.unit
    def test_publish_then_read_formatted(
        self,
        publisher: HandlerChatPublisher,
        reader: HandlerChatReader,
    ) -> None:
        """Published messages are readable via the reader."""
        msg = ModelAgentChatMessage(
            emitted_at=datetime(2026, 3, 25, 15, 0, 0, tzinfo=UTC),
            session_id="session-001",
            agent_id="epic-worker-1",
            message_type=EnumChatMessageType.PROGRESS,
            body="Wave 0 complete (1/10 tickets)",
            epic_id="OMN-3972",
            channel=EnumChatChannel.EPIC,
        )
        publisher.publish(msg)

        output = reader.read_formatted()
        assert "Wave 0 complete" in output
        assert "epic-worker-1" in output

    @pytest.mark.unit
    def test_multi_session_scenario(
        self,
        publisher: HandlerChatPublisher,
        reader: HandlerChatReader,
    ) -> None:
        """Multiple sessions writing to the same store are all visible."""
        for i in range(3):
            msg = ModelAgentChatMessage(
                emitted_at=datetime(2026, 3, 25, 15, i, 0, tzinfo=UTC),
                session_id=f"session-{i:03d}",
                agent_id=f"worker-{i}",
                message_type=EnumChatMessageType.STATUS,
                body=f"Worker {i} reporting in",
            )
            publisher.publish(msg)

        output = reader.read_formatted()
        for i in range(3):
            assert f"Worker {i} reporting in" in output

    @pytest.mark.unit
    def test_channel_filtering_pipeline(
        self,
        publisher: HandlerChatPublisher,
        reader: HandlerChatReader,
    ) -> None:
        """Channel filter works end-to-end through the pipeline."""
        publisher.publish(
            ModelAgentChatMessage(
                emitted_at=datetime.now(UTC),
                session_id="s1",
                agent_id="a1",
                message_type=EnumChatMessageType.STATUS,
                channel=EnumChatChannel.BROADCAST,
                body="broadcast msg",
            )
        )
        publisher.publish(
            ModelAgentChatMessage(
                emitted_at=datetime.now(UTC),
                session_id="s2",
                agent_id="ci-watcher",
                message_type=EnumChatMessageType.CI_ALERT,
                channel=EnumChatChannel.CI,
                severity=EnumChatSeverity.ERROR,
                body="Build failed",
            )
        )

        ci_output = reader.read_formatted(channel="CI")
        assert "Build failed" in ci_output
        assert "broadcast msg" not in ci_output

    @pytest.mark.unit
    def test_context_block_pipeline(
        self,
        publisher: HandlerChatPublisher,
        reader: HandlerChatReader,
    ) -> None:
        """Context block includes header and messages from publisher."""
        for i in range(5):
            publisher.publish(
                ModelAgentChatMessage(
                    emitted_at=datetime.now(UTC),
                    session_id="s1",
                    agent_id="worker",
                    message_type=EnumChatMessageType.PROGRESS,
                    body=f"Step {i} done",
                )
            )

        block = reader.read_context_block(n=3)
        assert "## Agent Chat (3 recent messages)" in block
        assert "Step 2 done" in block
        assert "Step 3 done" in block
        assert "Step 4 done" in block
        # Step 0 and 1 should be excluded (only last 3)
        assert "Step 0 done" not in block


class TestAutoEmitIntegration:
    """Tests for auto-emit convenience functions with a real store."""

    @pytest.mark.unit
    def test_emit_ci_alert(
        self, publisher: HandlerChatPublisher, store: HandlerFileChatStore
    ) -> None:
        result = emit_ci_alert(
            "Build failed on main",
            ticket_id="OMN-6527",
            publisher=publisher,
        )
        assert result is True
        messages = store.read_tail(n=1)
        assert len(messages) == 1
        assert messages[0].message_type == EnumChatMessageType.CI_ALERT
        assert messages[0].channel == EnumChatChannel.CI
        assert messages[0].severity == EnumChatSeverity.ERROR
        assert messages[0].body == "Build failed on main"

    @pytest.mark.unit
    def test_emit_status(
        self, publisher: HandlerChatPublisher, store: HandlerFileChatStore
    ) -> None:
        result = emit_status(
            "Worker started",
            publisher=publisher,
        )
        assert result is True
        messages = store.read_tail(n=1)
        assert messages[0].message_type == EnumChatMessageType.STATUS
        assert messages[0].channel == EnumChatChannel.BROADCAST

    @pytest.mark.unit
    def test_emit_progress_with_epic(
        self, publisher: HandlerChatPublisher, store: HandlerFileChatStore
    ) -> None:
        result = emit_progress(
            "Wave 1 complete",
            epic_id="OMN-3972",
            publisher=publisher,
        )
        assert result is True
        messages = store.read_tail(n=1)
        assert messages[0].message_type == EnumChatMessageType.PROGRESS
        assert messages[0].channel == EnumChatChannel.EPIC
        assert messages[0].epic_id == "OMN-3972"

    @pytest.mark.unit
    def test_emit_ci_alert_custom_severity(
        self, publisher: HandlerChatPublisher, store: HandlerFileChatStore
    ) -> None:
        emit_ci_alert(
            "Test flake detected",
            severity=EnumChatSeverity.WARN,
            publisher=publisher,
        )
        messages = store.read_tail(n=1)
        assert messages[0].severity == EnumChatSeverity.WARN
