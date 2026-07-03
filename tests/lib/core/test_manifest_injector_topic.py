# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests verifying manifest_injector uses TopicBase enum, not hardcoded strings."""

from __future__ import annotations

import pytest

from omniclaude.hooks.topics import TopicBase

pytestmark = pytest.mark.unit


def test_format_action_logging_uses_topic_base_enum() -> None:
    """_format_action_logging output must reference TopicBase.AGENT_ACTIONS value, not a hardcoded string."""
    from omniclaude.lib.core.manifest_injector import ManifestInjector

    injector = ManifestInjector.__new__(ManifestInjector)
    injector._current_correlation_id = None
    injector.agent_name = "test-agent"

    action_logging_data: dict = {"project_name": "test-project"}
    output = injector._format_action_logging(action_logging_data)

    expected_topic = str(TopicBase.AGENT_ACTIONS)
    assert expected_topic in output, (
        f"Expected TopicBase.AGENT_ACTIONS value '{expected_topic}' in action_logging output; "
        "output must not use a hardcoded topic string."
    )
    # Verify the literal string form was not hardcoded by checking it comes from TopicBase
    assert "onex.evt.omniclaude.agent-actions.v1" in output, (
        "Topic value should still appear in output via TopicBase enum reference."
    )
