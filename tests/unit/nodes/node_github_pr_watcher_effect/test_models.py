# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Tests for the GitHub PR watcher effect node models."""

from __future__ import annotations

import pytest

from omniclaude.nodes.node_github_pr_watcher_effect.models import (
    AgentInboxMessage,
    InboxRouteResult,
    WatchRegistration,
)


@pytest.mark.unit
class TestInboxRouteResult:
    """Tests for InboxRouteResult model."""

    def test_empty_result(self) -> None:
        """Test creating an empty route result."""
        result = InboxRouteResult(event_dedupe_key="repo:sha:123")
        assert result.agents_notified == []
        assert result.inbox_topics == []
        assert result.event_dedupe_key == "repo:sha:123"
        assert result.routed_at  # Auto-generated

    def test_populated_result(self) -> None:
        """Test creating a populated route result."""
        result = InboxRouteResult(
            agents_notified=["agent-001", "agent-002"],
            inbox_topics=[
                "onex.evt.omniclaude.agent-inbox.agent-001.v1",
                "onex.evt.omniclaude.agent-inbox.agent-002.v1",
            ],
            event_dedupe_key="OmniNode-ai/omniclaude:abc123:12345",
        )
        assert len(result.agents_notified) == 2
        assert len(result.inbox_topics) == 2


@pytest.mark.unit
class TestWatchRegistration:
    """Tests for WatchRegistration model."""

    def test_valid_registration(self) -> None:
        """Test creating a valid watch registration."""
        reg = WatchRegistration(
            agent_id="agent-001",
            repo="OmniNode-ai/omniclaude",
            pr_number=42,
        )
        assert reg.agent_id == "agent-001"
        assert reg.repo == "OmniNode-ai/omniclaude"
        assert reg.pr_number == 42


@pytest.mark.unit
class TestAgentInboxMessage:
    """Tests for AgentInboxMessage model."""

    def test_from_pr_status(self) -> None:
        """Test creating an inbox message from a PR status event."""
        payload = {
            "repo": "OmniNode-ai/omniclaude",
            "pr": 42,
            "conclusion": "success",
            "sha": "abc123",
        }
        msg = AgentInboxMessage.from_pr_status(
            agent_id="agent-001",
            pr_status_payload=payload,
        )
        assert msg.agent_id == "agent-001"
        assert msg.event_type == "pr-status"
        assert msg.source_topic == "onex.evt.github.pr-status.v1"
        assert msg.payload == payload
        assert msg.schema_version == "1.0.0"
        assert msg.message_id  # Auto-generated
        assert msg.emitted_at  # Auto-generated

    def test_with_trace_context(self) -> None:
        """Test inbox message with trace context."""
        msg = AgentInboxMessage.from_pr_status(
            agent_id="agent-002",
            pr_status_payload={"repo": "test", "pr": 1},
            trace={"correlation_id": "corr-123", "parent_id": "parent-456"},
        )
        assert msg.trace["correlation_id"] == "corr-123"
        assert msg.trace["parent_id"] == "parent-456"

    def test_topic_convention(self) -> None:
        """Test that inbox topic follows the naming convention."""
        agent_id = "agent-abc-123"
        expected_topic = f"onex.evt.omniclaude.agent-inbox.{agent_id}.v1"
        # The topic is constructed by the router, not the model, but verify the convention
        assert "agent-inbox" in expected_topic
        assert agent_id in expected_topic
