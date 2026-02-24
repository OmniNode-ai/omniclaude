# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Tests for OmniClaude topic names and helpers.

This module contains comprehensive tests for the build_topic() function
and TopicBase enum, including edge cases for invalid input types.
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
        # - producer: lowercase service name
        # - event-name: kebab-case
        # - version: v + integer
        onex_pattern = re.compile(
            r"^onex\.(cmd|evt|dlq|intent|snapshot)\.[a-z]+\.[a-z-]+\.v\d+$"
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
    """Tests for build_topic() with valid inputs."""

    def test_build_topic_with_prefix(self) -> None:
        """Build full topic name from prefix and base."""
        topic = build_topic("dev", TopicBase.SESSION_STARTED)
        assert topic == "dev.onex.evt.omniclaude.session-started.v1"

        topic = build_topic("prod", TopicBase.TOOL_EXECUTED)
        assert topic == "prod.onex.evt.omniclaude.tool-executed.v1"

    def test_build_topic_empty_prefix_returns_base(self) -> None:
        """Empty prefix returns just the base topic name."""
        topic = build_topic("", TopicBase.SESSION_STARTED)
        assert topic == "onex.evt.omniclaude.session-started.v1"

    def test_build_topic_whitespace_prefix_returns_base(self) -> None:
        """Whitespace-only prefix returns just the base topic name."""
        topic = build_topic("   ", TopicBase.SESSION_STARTED)
        assert topic == "onex.evt.omniclaude.session-started.v1"

        # Tab characters
        topic = build_topic("\t\t", TopicBase.SESSION_STARTED)
        assert topic == "onex.evt.omniclaude.session-started.v1"

        # Newline characters
        topic = build_topic("\n\n", TopicBase.SESSION_STARTED)
        assert topic == "onex.evt.omniclaude.session-started.v1"

        # Mixed whitespace
        topic = build_topic("  \t\n  ", TopicBase.SESSION_STARTED)
        assert topic == "onex.evt.omniclaude.session-started.v1"

    def test_build_topic_strips_whitespace(self) -> None:
        """Prefix and base whitespace is stripped."""
        topic = build_topic("  dev  ", "  omniclaude.test.v1  ")
        assert topic == "dev.omniclaude.test.v1"

    def test_build_topic_valid_characters(self) -> None:
        """Valid topic names with allowed characters."""
        # Alphanumeric, underscores, hyphens are allowed
        topic = build_topic("dev-test_1", "omniclaude.session_started.v1")
        assert topic == "dev-test_1.omniclaude.session_started.v1"

    def test_build_topic_all_topic_bases(self) -> None:
        """All TopicBase values work with build_topic."""
        for base in TopicBase:
            topic = build_topic("dev", base)
            assert topic == f"dev.{base.value}"


# =============================================================================
# build_topic() Invalid Prefix Type Tests
# =============================================================================


class TestBuildTopicInvalidPrefixTypes:
    """Tests for build_topic() with invalid prefix types."""

    def test_build_topic_none_prefix_raises(self) -> None:
        """None prefix raises ModelOnexError with clear message."""
        with pytest.raises(ModelOnexError, match="prefix must not be None"):
            build_topic(None, TopicBase.SESSION_STARTED)  # type: ignore[arg-type]

    def test_build_topic_int_prefix_raises(self) -> None:
        """Integer prefix raises ModelOnexError with clear type message."""
        with pytest.raises(ModelOnexError, match="prefix must be a string, got int"):
            build_topic(123, TopicBase.SESSION_STARTED)  # type: ignore[arg-type]

    def test_build_topic_float_prefix_raises(self) -> None:
        """Float prefix raises ModelOnexError with clear type message."""
        with pytest.raises(ModelOnexError, match="prefix must be a string, got float"):
            build_topic(3.14, TopicBase.SESSION_STARTED)  # type: ignore[arg-type]

    def test_build_topic_list_prefix_raises(self) -> None:
        """List prefix raises ModelOnexError with clear type message."""
        with pytest.raises(ModelOnexError, match="prefix must be a string, got list"):
            build_topic(["dev"], TopicBase.SESSION_STARTED)  # type: ignore[arg-type]

    def test_build_topic_dict_prefix_raises(self) -> None:
        """Dict prefix raises ModelOnexError with clear type message."""
        with pytest.raises(ModelOnexError, match="prefix must be a string, got dict"):
            build_topic({"env": "dev"}, TopicBase.SESSION_STARTED)  # type: ignore[arg-type]

    def test_build_topic_tuple_prefix_raises(self) -> None:
        """Tuple prefix raises ModelOnexError with clear type message."""
        with pytest.raises(ModelOnexError, match="prefix must be a string, got tuple"):
            build_topic(("dev",), TopicBase.SESSION_STARTED)  # type: ignore[arg-type]

    def test_build_topic_bytes_prefix_raises(self) -> None:
        """Bytes prefix raises ModelOnexError with clear type message."""
        with pytest.raises(ModelOnexError, match="prefix must be a string, got bytes"):
            build_topic(b"dev", TopicBase.SESSION_STARTED)  # type: ignore[arg-type]

    def test_build_topic_bool_prefix_raises(self) -> None:
        """Bool prefix raises ModelOnexError with clear type message."""
        with pytest.raises(ModelOnexError, match="prefix must be a string, got bool"):
            build_topic(True, TopicBase.SESSION_STARTED)  # type: ignore[arg-type]


# =============================================================================
# build_topic() Invalid Base Tests
# =============================================================================


class TestBuildTopicInvalidBase:
    """Tests for build_topic() with invalid base values."""

    def test_build_topic_empty_base_raises(self) -> None:
        """Empty base raises ModelOnexError."""
        with pytest.raises(ModelOnexError, match="base must be a non-empty string"):
            build_topic("dev", "")

    def test_build_topic_none_base_raises(self) -> None:
        """None base raises ModelOnexError with clear message."""
        with pytest.raises(ModelOnexError, match="base must not be None"):
            build_topic("dev", None)  # type: ignore[arg-type]

    def test_build_topic_whitespace_base_raises(self) -> None:
        """Whitespace-only base raises ModelOnexError."""
        with pytest.raises(ModelOnexError, match="base must be a non-empty string"):
            build_topic("dev", "   ")

    def test_build_topic_int_base_raises(self) -> None:
        """Integer base raises ModelOnexError with clear type message."""
        with pytest.raises(ModelOnexError, match="base must be a string, got int"):
            build_topic("dev", 123)  # type: ignore[arg-type]


# =============================================================================
# build_topic() Malformed Topic Tests
# =============================================================================


class TestBuildTopicMalformedTopics:
    """Tests for build_topic() with malformed topic patterns."""

    def test_build_topic_rejects_leading_dot_in_base(self) -> None:
        """Base with leading dot produces malformed topic (rejected)."""
        with pytest.raises(ModelOnexError, match="consecutive dots"):
            build_topic("dev", ".omniclaude.test.v1")

    def test_build_topic_rejects_trailing_dot_in_base(self) -> None:
        """Base with trailing dot produces malformed topic (rejected)."""
        with pytest.raises(ModelOnexError, match="must not end with a dot"):
            build_topic("dev", "omniclaude.test.v1.")

    def test_build_topic_rejects_consecutive_dots(self) -> None:
        """Topic with consecutive dots is rejected."""
        with pytest.raises(ModelOnexError, match="consecutive dots"):
            build_topic("dev", "omniclaude..test.v1")

    def test_build_topic_rejects_special_characters_in_prefix(self) -> None:
        """Topic prefix with special characters is rejected."""
        with pytest.raises(ModelOnexError, match="invalid characters"):
            build_topic("dev@test", TopicBase.SESSION_STARTED)

        with pytest.raises(ModelOnexError, match="invalid characters"):
            build_topic("dev#test", TopicBase.SESSION_STARTED)

        with pytest.raises(ModelOnexError, match="invalid characters"):
            build_topic("dev$test", TopicBase.SESSION_STARTED)

        with pytest.raises(ModelOnexError, match="invalid characters"):
            build_topic("dev%test", TopicBase.SESSION_STARTED)

        with pytest.raises(ModelOnexError, match="invalid characters"):
            build_topic("dev*test", TopicBase.SESSION_STARTED)

    def test_build_topic_rejects_special_characters_in_base(self) -> None:
        """Topic base with special characters is rejected."""
        with pytest.raises(ModelOnexError, match="invalid characters"):
            build_topic("dev", "omniclaude.test#v1")

        with pytest.raises(ModelOnexError, match="invalid characters"):
            build_topic("dev", "omniclaude.test@v1")

    def test_build_topic_rejects_dots_in_prefix(self) -> None:
        """Prefix with dots is rejected."""
        with pytest.raises(ModelOnexError, match="prefix must not contain dots"):
            build_topic("dev.staging", TopicBase.SESSION_STARTED)

        with pytest.raises(ModelOnexError, match="prefix must not contain dots"):
            build_topic("a.b.c", TopicBase.SESSION_STARTED)


# =============================================================================
# build_topic() Edge Cases
# =============================================================================


class TestBuildTopicEdgeCases:
    """Edge case tests for build_topic()."""

    def test_build_topic_single_char_prefix(self) -> None:
        """Single character prefix is valid."""
        topic = build_topic("d", TopicBase.SESSION_STARTED)
        assert topic == "d.onex.evt.omniclaude.session-started.v1"

    def test_build_topic_numeric_prefix(self) -> None:
        """Numeric string prefix is valid."""
        topic = build_topic("123", TopicBase.SESSION_STARTED)
        assert topic == "123.onex.evt.omniclaude.session-started.v1"

    def test_build_topic_long_prefix(self) -> None:
        """Long prefix is valid."""
        long_prefix = "a" * 100
        topic = build_topic(long_prefix, TopicBase.SESSION_STARTED)
        assert topic == f"{long_prefix}.onex.evt.omniclaude.session-started.v1"

    def test_build_topic_unicode_prefix_rejected(self) -> None:
        """Unicode characters in prefix are rejected."""
        with pytest.raises(ModelOnexError, match="invalid characters"):
            build_topic("dev-\u00e9", TopicBase.SESSION_STARTED)  # dev-e with accent

    def test_build_topic_preserves_case_in_prefix(self) -> None:
        """Prefix case is preserved (not forced to lowercase)."""
        topic = build_topic("DEV", TopicBase.SESSION_STARTED)
        assert topic == "DEV.onex.evt.omniclaude.session-started.v1"

        topic = build_topic("Dev_Test", TopicBase.SESSION_STARTED)
        assert topic == "Dev_Test.onex.evt.omniclaude.session-started.v1"
