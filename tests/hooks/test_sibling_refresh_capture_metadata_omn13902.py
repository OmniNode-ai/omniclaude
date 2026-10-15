# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The refreshed sibling's metadata policy survives the hook-event fan-out."""

from __future__ import annotations

from copy import deepcopy

import pytest

from omniclaude.hooks.capture_redaction import hash_value
from omniclaude.hooks.event_registry import EVENT_REGISTRY

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("hook_event_name", "metadata"),
    [
        (
            "GuardRefusal",
            {
                "guard": "pre_tool_use_worktree_guard.sh",
                "reason_class": "worktree_refused",
                "refused_hook_event_name": "PreToolUse",
            },
        ),
        (
            "AssistantUsage",
            {
                "message_count": 2,
                "input_tokens": 120,
                "output_tokens": 30,
                "cache_creation_input_tokens": 10,
                "cache_read_input_tokens": 90,
                "usage_source_hook": "Stop",
                "partial_window": True,
            },
        ),
        (
            "AssistantUsage",
            {
                "message_count": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
                "usage_source_hook": "Stop",
                "partial_window": False,
            },
        ),
    ],
    ids=["guard-refusal", "assistant-usage", "empty-usage-window"],
)
def test_refreshed_metadata_crosses_without_exposing_undeclared_content(
    hook_event_name: str, metadata: dict[str, object]
) -> None:
    record: dict[str, object] = {
        "hook_event_name": hook_event_name,
        "payload": {**metadata, "undeclared_content": "private hook text"},
    }
    original = deepcopy(record)
    rule = next(
        rule
        for rule in EVENT_REGISTRY["hook.event"].fan_out
        if rule.topic_base.value == "onex.evt.omniclaude.hook-event.v1"
    )

    result = rule.apply_transform(record)

    assert result["hook_event_name"] == hook_event_name
    assert result["payload"] == {
        **metadata,
        "undeclared_content": hash_value("private hook text"),
    }
    assert result["redaction_state"] == "redacted"
    assert record == original
