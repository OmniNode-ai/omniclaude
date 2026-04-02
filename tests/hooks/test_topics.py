# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for OmniClaude topic names and helpers.

Comprehensive tests for the build_topic() function and TopicBase enum,
including edge cases for invalid input types.
"""

from __future__ import annotations

import pytest
from omnibase_core.models.errors import ModelOnexError

from omniclaude.hooks.topics import TopicBase, build_topic

# All tests in this module are unit tests
pytestmark = pytest.mark.unit

# =============================================================================
# Topic Base Tests
# =============================================================================


class TestTopicBase:
    """Tests for TopicBase enum values."""

    def test_topic_base_names(self) -> None:
        """Topic base names follow ONEX canonical format (OMN-1537)."""
        # omniclaude event topics (onex.evt.omniclaude.{event-name}.v1)
        assert TopicBase.SESSION_STARTED == "onex.evt.omniclaude.session-started.v1"
        assert TopicBase.SESSION_ENDED == "onex.evt.omniclaude.session-ended.v1"
        assert TopicBase.PROMPT_SUBMITTED == "onex.evt.omniclaude.prompt-submitted.v1"
        assert TopicBase.TOOL_EXECUTED == "onex.evt.omniclaude.tool-executed.v1"
        assert TopicBase.AGENT_ACTION == "onex.evt.omniclaude.agent-action.v1"
        assert TopicBase.LEARNING_PATTERN == "onex.evt.omniclaude.learning-pattern.v1"

        # omninode routing topics (onex.cmd/evt.omninode.{event-name}.v1)
        assert TopicBase.ROUTING_REQUESTED == "onex.cmd.omninode.routing-requested.v1"
        assert TopicBase.ROUTING_COMPLETED == "onex.evt.omninode.routing-completed.v1"
        assert TopicBase.ROUTING_FAILED == "onex.evt.omninode.routing-failed.v1"

        # Cross-service topics (omniclaude → omniintelligence)
        assert (
            TopicBase.CLAUDE_HOOK_EVENT
            == "onex.cmd.omniintelligence.claude-hook-event.v1"
        )

        # Hook adapter observability topics (migrated to ONEX format, OMN-1552)
        assert TopicBase.AGENT_ACTIONS == "onex.evt.omniclaude.agent-actions.v1"
        assert (
            TopicBase.PERFORMANCE_METRICS
            == "onex.evt.omniclaude.performance-metrics.v1"
        )
        assert (
            TopicBase.TRANSFORMATIONS == "onex.evt.omniclaude.agent-transformation.v1"
        )
        assert (
            TopicBase.DETECTION_FAILURES == "onex.evt.omniclaude.detection-failure.v1"
        )

        # Execution and observability topics (OMN-1552 migration)
        assert TopicBase.EXECUTION_LOGS == "onex.evt.omniclaude.agent-execution-logs.v1"
        assert (
            TopicBase.AGENT_OBSERVABILITY
            == "onex.evt.omniclaude.agent-observability.v1"
        )
        # DLQ topic for agent observability consumer (OMN-2959)
        assert (
            TopicBase.AGENT_OBSERVABILITY_DLQ
            == "onex.evt.omniclaude.agent-observability-dlq.v1"
        )

    def test_topic_base_is_str_enum(self) -> None:
        """TopicBase values are strings (StrEnum)."""
        for topic in TopicBase:
            assert isinstance(topic, str)
            assert isinstance(topic.value, str)

    def test_all_topics_follow_naming_convention(self) -> None:
        """Topics follow ONEX canonical format (OMN-1537) or legacy naming."""
        import re

        # ONEX canonical format (OMN-1537): onex.{kind}.{producer}.{event-name}.v{n}
        # - Exactly 5 dot-separated segments
        # - kind: cmd, evt, dlq, intent, snapshot
        # - producer: lowercase service name (may contain hyphens for infra services)
        # - event-name: kebab-case
        # - version: v + integer
        onex_pattern = re.compile(
            r"^onex\.(cmd|evt|dlq|intent|snapshot)\.[a-z][a-z0-9-]*\.[a-z-]+\.v\d+$"
        )

        # All topics now follow ONEX canonical format (OMN-1552 migrated legacy topics)
        for topic in TopicBase:
            # ONEX canonical format: onex.{kind}.{producer}.{event-name}.v{n}
            assert onex_pattern.match(topic.value), (
                f"Topic {topic.name} does not follow ONEX canonical format: {topic.value}"
            )


# =============================================================================
# build_topic() Valid Input Tests
# =============================================================================


class TestBuildTopicValidInputs:
    """Tests for build_topic() with valid inputs (prefix removed in OMN-5212)."""

    def test_build_topic_returns_canonical_name(self) -> None:
        """build_topic returns the canonical topic name."""
        topic = build_topic(TopicBase.SESSION_STARTED)
        assert topic == "onex.evt.omniclaude.session-started.v1"

        topic = build_topic(TopicBase.TOOL_EXECUTED)
        assert topic == "onex.evt.omniclaude.tool-executed.v1"

    def test_build_topic_all_topic_bases(self) -> None:
        """All TopicBase values work with build_topic."""
        for base in TopicBase:
            topic = build_topic(base)
            assert topic == base.value


# =============================================================================
# build_topic() Invalid Base Tests
# =============================================================================


class TestBuildTopicInvalidBase:
    """Tests for build_topic() with invalid base values."""

    def test_build_topic_empty_base_raises(self) -> None:
        """Empty base raises ModelOnexError."""
        with pytest.raises(ModelOnexError, match="base must be a non-empty string"):
            build_topic("")

    def test_build_topic_none_base_raises(self) -> None:
        """None base raises ModelOnexError with clear message."""
        with pytest.raises(ModelOnexError, match="base must not be None"):
            build_topic(None)  # type: ignore[arg-type]

    def test_build_topic_whitespace_base_raises(self) -> None:
        """Whitespace-only base raises ModelOnexError."""
        with pytest.raises(ModelOnexError, match="base must be a non-empty string"):
            build_topic("   ")

    def test_build_topic_int_base_raises(self) -> None:
        """Integer base raises ModelOnexError with clear type message."""
        with pytest.raises(ModelOnexError, match="base must be a string, got int"):
            build_topic(123)  # type: ignore[arg-type]


# =============================================================================
# build_topic() Malformed Topic Tests
# =============================================================================


class TestBuildTopicMalformedTopics:
    """Tests for build_topic() with malformed topic patterns."""

    def test_build_topic_rejects_leading_dot_in_base(self) -> None:
        """Base with leading dot is rejected."""
        with pytest.raises(ModelOnexError, match="must not start with a dot"):
            build_topic(".omniclaude.test.v1")

    def test_build_topic_rejects_trailing_dot_in_base(self) -> None:
        """Base with trailing dot is rejected."""
        with pytest.raises(ModelOnexError, match="must not end with a dot"):
            build_topic("omniclaude.test.v1.")

    def test_build_topic_rejects_consecutive_dots(self) -> None:
        """Topic with consecutive dots is rejected."""
        with pytest.raises(ModelOnexError, match="consecutive dots"):
            build_topic("omniclaude..test.v1")

    def test_build_topic_rejects_special_characters_in_base(self) -> None:
        """Topic base with special characters is rejected."""
        with pytest.raises(ModelOnexError, match="invalid characters"):
            build_topic("omniclaude.test#v1")

        with pytest.raises(ModelOnexError, match="invalid characters"):
            build_topic("omniclaude.test@v1")
