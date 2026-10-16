# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Capture metadata policy and the refreshed sibling's raw fan-out (OMN-13902)."""

from __future__ import annotations

from copy import deepcopy

import pytest

from omniclaude.hooks.capture_redaction import hash_value, redact_capture
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
def test_redaction_policy_preserves_metadata_when_explicitly_applied(
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

    result = redact_capture(record, topic=rule.topic_base.value)

    assert result["hook_event_name"] == hook_event_name
    assert result["payload"] == {
        **metadata,
        "undeclared_content": hash_value("private hook text"),
    }
    assert result["redaction_state"] == "redacted"
    assert record == original


@pytest.mark.parametrize(
    ("topic", "declared"),
    [
        (
            "onex.evt.omniclaude.hook-event.v1",
            {"producer_seq": 0, "stream": "lineage"},
        ),
        (
            "onex.cmd.omniintelligence.content-captured.v1",
            {
                "content_record_id": "record-1",
                "producer_seq": 0,
                "stream": "content",
                "record_type": "barrier",
                "barrier_id": "barrier-1",
                "high_water": 0,
                "content_capture": False,
            },
        ),
    ],
    ids=["hook-lineage-sequence", "content-sequence-and-barrier"],
)
def test_redaction_policy_keeps_sequence_and_barrier_fields_verbatim(
    topic: str, declared: dict[str, object]
) -> None:
    """The OMN-18531 fields this refresh declares are not hashed by the policy."""
    record: dict[str, object] = {**declared, "undeclared_content": "private text"}
    original = deepcopy(record)

    result = redact_capture(record, topic=topic)

    for field, value in declared.items():
        assert result[field] == value, field
    assert result["undeclared_content"] == hash_value("private text")
    assert result["redaction_state"] == "redacted"
    assert record == original


@pytest.mark.parametrize(
    ("event_type", "topic", "payload"),
    [
        (
            "hook.event",
            "onex.evt.omniclaude.hook-event.v1",
            {
                "session_id": "session-1",
                "event_id": "event-1",
                "hook_event_name": "GuardRefusal",
                "lineage": {"session_id": "session-1", "agent_id": "agent-1"},
                "producer_seq": 0,
                "stream": "lineage",
                "payload": {
                    "guard": "worktree_guard",
                    "reason_class": "worktree_refused",
                    "undeclared_content": "complete hook payload",
                },
            },
        ),
        (
            "content.captured",
            "onex.cmd.omniintelligence.content-captured.v1",
            {
                "session_id": "session-1",
                "content_kind": "tool_result",
                "content_record_id": "record-1",
                "producer_seq": 0,
                "stream": "content",
                "content": "complete tool result",
            },
        ),
        (
            "content.captured",
            "onex.cmd.omniintelligence.content-captured.v1",
            {
                "session_id": "session-1",
                "content_kind": "barrier",
                "record_type": "barrier",
                "barrier_id": "barrier-1",
                "stream": "content",
                "high_water": 0,
                "content_capture": False,
            },
        ),
    ],
    ids=["hook-lineage", "full-content", "empty-content-barrier"],
)
def test_refreshed_capture_fan_out_preserves_raw_records(
    event_type: str, topic: str, payload: dict[str, object]
) -> None:
    """OMN-19513's pinned registry declares no hashing on either capture route."""
    registration = EVENT_REGISTRY[event_type]
    assert registration.partition_key_field == "session_id"
    assert len(registration.fan_out) == 1
    rule = registration.fan_out[0]
    assert rule.topic_base.value == topic
    original = deepcopy(payload)

    result = rule.apply_transform(payload)

    assert result == original
    assert result is not payload
    assert payload == original
    assert rule.transform is None
