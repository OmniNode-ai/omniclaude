# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests for event_registry module.

This module tests the event registry that defines daemon routing and fan-out rules
for Claude Code hook events. The registry supports:
- Fan-out: Publishing one event to multiple topics with different payloads
- Payload transforms: Modifying payload before publishing (e.g., sanitization)
- Partition keys: Extracting keys for Kafka ordering guarantees
- Required field validation: Ensuring payloads have necessary fields
"""

from __future__ import annotations

import pytest

from omniclaude.hooks.topics import TopicBase

# All tests in this module are unit tests
pytestmark = pytest.mark.unit


# =============================================================================
# Module Import Tests
# =============================================================================


class TestModuleImports:
    """Tests verifying module can be imported correctly."""

    def test_module_imports(self) -> None:
        """Verify module can be imported."""
        from omniclaude.hooks import event_registry

        assert event_registry is not None

    def test_import_event_registry_dict(self) -> None:
        """Verify EVENT_REGISTRY can be imported."""
        from omniclaude.hooks.event_registry import EVENT_REGISTRY

        assert EVENT_REGISTRY is not None
        assert isinstance(EVENT_REGISTRY, dict)

    def test_import_helper_functions(self) -> None:
        """Verify all helper functions can be imported."""
        from omniclaude.hooks.event_registry import (
            get_partition_key,
            get_registration,
            list_event_types,
            validate_payload,
        )

        assert callable(get_registration)
        assert callable(list_event_types)
        assert callable(validate_payload)
        assert callable(get_partition_key)

    def test_import_transform_functions(self) -> None:
        """Verify transform functions can be imported."""
        from omniclaude.hooks.event_registry import (
            transform_for_observability,
            transform_passthrough,
        )

        assert callable(transform_for_observability)
        assert callable(transform_passthrough)

    def test_import_dataclasses(self) -> None:
        """Verify dataclasses can be imported."""
        from omniclaude.hooks.event_registry import EventRegistration, FanOutRule

        assert EventRegistration is not None
        assert FanOutRule is not None

    def test_all_exports(self) -> None:
        """Verify __all__ exports are accessible."""
        from omniclaude.hooks.event_registry import __all__

        expected_exports = [
            "transform_for_observability",
            "transform_passthrough",
            "FanOutRule",
            "EventRegistration",
            "EVENT_REGISTRY",
            "get_registration",
            "list_event_types",
            "validate_payload",
            "get_partition_key",
            "PayloadTransform",
        ]
        for export in expected_exports:
            assert export in __all__, f"Missing export: {export}"


# =============================================================================
# list_event_types() Tests
# =============================================================================


class TestListEventTypes:
    """Tests for list_event_types() function."""

    def test_list_event_types_returns_list(self) -> None:
        """Verify list_event_types returns a list."""
        from omniclaude.hooks.event_registry import list_event_types

        types = list_event_types()
        assert isinstance(types, list)

    def test_list_event_types_contains_session_events(self) -> None:
        """Verify session events are registered."""
        from omniclaude.hooks.event_registry import list_event_types

        types = list_event_types()
        assert "session.started" in types
        assert "session.ended" in types

    def test_list_event_types_contains_prompt_events(self) -> None:
        """Verify prompt events are registered."""
        from omniclaude.hooks.event_registry import list_event_types

        types = list_event_types()
        assert "prompt.submitted" in types

    def test_list_event_types_contains_tool_events(self) -> None:
        """Verify tool events are registered."""
        from omniclaude.hooks.event_registry import list_event_types

        types = list_event_types()
        assert "tool.executed" in types

    def test_list_event_types_all_strings(self) -> None:
        """Verify all event types are strings."""
        from omniclaude.hooks.event_registry import list_event_types

        types = list_event_types()
        for event_type in types:
            assert isinstance(event_type, str)

    def test_list_event_types_at_least_four_types(self) -> None:
        """Verify at least 4 event types are registered."""
        from omniclaude.hooks.event_registry import list_event_types

        types = list_event_types()
        # session.started, session.ended, prompt.submitted, tool.executed
        assert len(types) >= 4


# =============================================================================
# get_registration() Tests
# =============================================================================


class TestGetRegistration:
    """Tests for get_registration() function."""

    def test_get_registration_returns_registration(self) -> None:
        """Verify get_registration returns EventRegistration for valid type."""
        from omniclaude.hooks.event_registry import EventRegistration, get_registration

        reg = get_registration("session.started")
        assert reg is not None
        assert isinstance(reg, EventRegistration)

    def test_get_registration_returns_none_for_unknown(self) -> None:
        """Verify get_registration returns None for unknown event type."""
        from omniclaude.hooks.event_registry import get_registration

        reg = get_registration("unknown.event.type")
        assert reg is None

    def test_get_registration_session_started(self) -> None:
        """Verify session.started registration is correct."""
        from omniclaude.hooks.event_registry import get_registration

        reg = get_registration("session.started")
        assert reg is not None
        assert reg.event_type == "session.started"
        assert reg.partition_key_field == "session_id"
        assert "session_id" in reg.required_fields
        assert len(reg.fan_out) == 1

    def test_get_registration_session_ended(self) -> None:
        """Verify session.ended registration is correct."""
        from omniclaude.hooks.event_registry import get_registration

        reg = get_registration("session.ended")
        assert reg is not None
        assert reg.event_type == "session.ended"
        assert reg.partition_key_field == "session_id"
        assert "session_id" in reg.required_fields

    def test_get_registration_prompt_submitted_has_fan_out(self) -> None:
        """Verify prompt.submitted has fan-out to multiple topics."""
        from omniclaude.hooks.event_registry import get_registration

        reg = get_registration("prompt.submitted")
        assert reg is not None
        assert reg.event_type == "prompt.submitted"
        # Should fan-out to both intelligence and observability topics
        assert len(reg.fan_out) == 2

    def test_get_registration_prompt_submitted_required_fields(self) -> None:
        """Verify prompt.submitted requires prompt_preview and session_id."""
        from omniclaude.hooks.event_registry import get_registration

        reg = get_registration("prompt.submitted")
        assert reg is not None
        assert "prompt_preview" in reg.required_fields
        assert "session_id" in reg.required_fields

    def test_get_registration_tool_executed(self) -> None:
        """Verify tool.executed registration is correct."""
        from omniclaude.hooks.event_registry import get_registration

        reg = get_registration("tool.executed")
        assert reg is not None
        assert reg.event_type == "tool.executed"
        assert "tool_name" in reg.required_fields


# =============================================================================
# validate_payload() Tests
# =============================================================================


class TestValidatePayload:
    """Tests for validate_payload() function."""

    def test_validate_payload_returns_missing_fields(self) -> None:
        """Verify validate_payload returns list of missing fields."""
        from omniclaude.hooks.event_registry import validate_payload

        missing = validate_payload("prompt.submitted", {"prompt_preview": "hello"})
        assert isinstance(missing, list)
        assert "session_id" in missing

    def test_validate_payload_empty_for_valid(self) -> None:
        """Verify validate_payload returns empty list for valid payload."""
        from omniclaude.hooks.event_registry import validate_payload

        missing = validate_payload(
            "prompt.submitted", {"prompt_preview": "hello", "session_id": "xyz"}
        )
        assert len(missing) == 0

    def test_validate_payload_session_started(self) -> None:
        """Verify session.started validation."""
        from omniclaude.hooks.event_registry import validate_payload

        # Missing session_id
        missing = validate_payload("session.started", {})
        assert "session_id" in missing

        # Valid
        missing = validate_payload("session.started", {"session_id": "abc123"})
        assert len(missing) == 0

    def test_validate_payload_tool_executed(self) -> None:
        """Verify tool.executed validation."""
        from omniclaude.hooks.event_registry import validate_payload

        # Missing tool_name
        missing = validate_payload("tool.executed", {"session_id": "abc"})
        assert "tool_name" in missing

        # Missing session_id
        missing = validate_payload("tool.executed", {"tool_name": "Read"})
        assert "session_id" in missing

        # Valid (both tool_name and session_id required)
        missing = validate_payload(
            "tool.executed", {"tool_name": "Read", "session_id": "abc"}
        )
        assert len(missing) == 0

    def test_validate_payload_raises_for_unknown_type(self) -> None:
        """Verify validate_payload raises KeyError for unknown event type."""
        from omniclaude.hooks.event_registry import validate_payload

        with pytest.raises(KeyError, match="Unknown event type"):
            validate_payload("unknown.event", {"foo": "bar"})

    def test_validate_payload_multiple_missing(self) -> None:
        """Verify validate_payload returns all missing fields."""
        from omniclaude.hooks.event_registry import validate_payload

        # prompt.submitted requires both prompt_preview and session_id
        missing = validate_payload("prompt.submitted", {})
        assert "prompt_preview" in missing
        assert "session_id" in missing

    def test_validate_payload_extra_fields_ignored(self) -> None:
        """Verify extra fields in payload are ignored."""
        from omniclaude.hooks.event_registry import validate_payload

        missing = validate_payload(
            "session.started",
            {"session_id": "abc", "extra_field": "value", "another": 123},
        )
        assert len(missing) == 0


# =============================================================================
# get_partition_key() Tests
# =============================================================================


class TestGetPartitionKey:
    """Tests for get_partition_key() function."""

    def test_get_partition_key_extracts_session_id(self) -> None:
        """Verify get_partition_key extracts session_id."""
        from omniclaude.hooks.event_registry import get_partition_key

        key = get_partition_key(
            "prompt.submitted", {"session_id": "abc123", "prompt": "hello"}
        )
        assert key == "abc123"

    def test_get_partition_key_returns_string(self) -> None:
        """Verify get_partition_key returns string."""
        from omniclaude.hooks.event_registry import get_partition_key

        key = get_partition_key("session.started", {"session_id": "test-session"})
        assert isinstance(key, str)
        assert key == "test-session"

    def test_get_partition_key_converts_non_string(self) -> None:
        """Verify get_partition_key converts non-string values to string."""
        from omniclaude.hooks.event_registry import get_partition_key

        # Integer value
        key = get_partition_key("session.started", {"session_id": 12345})
        assert key == "12345"

        # UUID-like object (simulated)
        class FakeUUID:
            def __str__(self) -> str:
                return "fake-uuid-string"

        key = get_partition_key("session.started", {"session_id": FakeUUID()})
        assert key == "fake-uuid-string"

    def test_get_partition_key_returns_none_for_missing_field(self) -> None:
        """Verify get_partition_key returns None if field is missing."""
        from omniclaude.hooks.event_registry import get_partition_key

        key = get_partition_key("session.started", {"other_field": "value"})
        assert key is None

    def test_get_partition_key_returns_none_for_none_value(self) -> None:
        """Verify get_partition_key returns None if field value is None."""
        from omniclaude.hooks.event_registry import get_partition_key

        key = get_partition_key("session.started", {"session_id": None})
        assert key is None

    def test_get_partition_key_raises_for_unknown_type(self) -> None:
        """Verify get_partition_key raises KeyError for unknown event type."""
        from omniclaude.hooks.event_registry import get_partition_key

        with pytest.raises(KeyError, match="Unknown event type"):
            get_partition_key("unknown.event", {"session_id": "abc"})

    def test_get_partition_key_all_event_types(self) -> None:
        """Verify get_partition_key works for all registered event types."""
        from omniclaude.hooks.event_registry import get_partition_key, list_event_types

        for event_type in list_event_types():
            # Should not raise even with empty payload
            key = get_partition_key(event_type, {})
            # Key might be None if field is missing, but should not raise
            assert key is None or isinstance(key, str)


# =============================================================================
# transform_for_observability() Tests
# =============================================================================


class TestTransformForObservability:
    """Tests for transform_for_observability() function."""

    def test_transform_removes_full_prompt(self) -> None:
        """Verify observability transform removes full prompt."""
        from omniclaude.hooks.event_registry import transform_for_observability

        payload = {"prompt": "Hello world", "session_id": "abc123"}
        result = transform_for_observability(payload)
        assert "prompt" not in result

    def test_transform_adds_prompt_preview(self) -> None:
        """Verify observability transform adds prompt_preview."""
        from omniclaude.hooks.event_registry import transform_for_observability

        payload = {"prompt": "Hello world", "session_id": "abc123"}
        result = transform_for_observability(payload)
        assert "prompt_preview" in result
        assert result["prompt_preview"] == "Hello world"

    def test_transform_adds_prompt_length(self) -> None:
        """Verify observability transform adds prompt_length."""
        from omniclaude.hooks.event_registry import transform_for_observability

        payload = {"prompt": "Hello world", "session_id": "abc123"}
        result = transform_for_observability(payload)
        assert "prompt_length" in result
        assert result["prompt_length"] == 11  # len("Hello world")

    def test_transform_preserves_other_fields(self) -> None:
        """Verify observability transform preserves other fields."""
        from omniclaude.hooks.event_registry import transform_for_observability

        payload = {
            "prompt": "Hello",
            "session_id": "abc123",
            "correlation_id": "xyz",
            "timestamp": "2025-01-01",
        }
        result = transform_for_observability(payload)
        assert result["session_id"] == "abc123"
        assert result["correlation_id"] == "xyz"
        assert result["timestamp"] == "2025-01-01"

    def test_transform_truncates_long_prompt(self) -> None:
        """Verify observability transform truncates long prompts."""
        from omniclaude.hooks.event_registry import transform_for_observability
        from omniclaude.hooks.schemas import PROMPT_PREVIEW_MAX_LENGTH

        long_prompt = "x" * 200
        payload = {"prompt": long_prompt, "session_id": "abc"}
        result = transform_for_observability(payload)

        # Preview should be truncated to max length
        assert len(result["prompt_preview"]) == PROMPT_PREVIEW_MAX_LENGTH
        # Length should record original length
        assert result["prompt_length"] == 200

    def test_transform_sanitizes_secrets(self) -> None:
        """Verify observability transform sanitizes secrets."""
        from omniclaude.hooks.event_registry import transform_for_observability

        payload = {
            "prompt": "Use API key sk-1234567890abcdefghij",
            "session_id": "abc",
        }
        result = transform_for_observability(payload)

        # Secret should be redacted
        assert "sk-1234567890abcdefghij" not in result["prompt_preview"]
        assert "REDACTED" in result["prompt_preview"]

    def test_transform_handles_empty_prompt(self) -> None:
        """Verify observability transform handles empty prompt."""
        from omniclaude.hooks.event_registry import transform_for_observability

        payload = {"prompt": "", "session_id": "abc"}
        result = transform_for_observability(payload)

        assert result["prompt_preview"] == ""
        assert result["prompt_length"] == 0

    def test_transform_handles_missing_prompt(self) -> None:
        """Verify observability transform handles missing prompt."""
        from omniclaude.hooks.event_registry import transform_for_observability

        payload = {"session_id": "abc"}
        result = transform_for_observability(payload)

        assert result["prompt_preview"] == ""
        assert result["prompt_length"] == 0

    def test_transform_handles_non_string_prompt(self) -> None:
        """Verify observability transform handles non-string prompt."""
        from omniclaude.hooks.event_registry import transform_for_observability

        # Integer prompt
        payload = {"prompt": 12345, "session_id": "abc"}
        result = transform_for_observability(payload)
        assert result["prompt_preview"] == "12345"
        assert result["prompt_length"] == 5

    def test_transform_handles_none_prompt(self) -> None:
        """Verify observability transform handles None prompt."""
        from omniclaude.hooks.event_registry import transform_for_observability

        payload = {"prompt": None, "session_id": "abc"}
        result = transform_for_observability(payload)

        assert result["prompt_preview"] == ""
        assert result["prompt_length"] == 0

    def test_transform_does_not_mutate_original(self) -> None:
        """Verify observability transform does not mutate original payload."""
        from omniclaude.hooks.event_registry import transform_for_observability

        original = {"prompt": "Hello world", "session_id": "abc123"}
        original_copy = dict(original)

        transform_for_observability(original)

        # Original should be unchanged
        assert original == original_copy

    def test_transform_new_payload_strips_prompt_b64(self) -> None:
        """New payload shape: prompt_b64 is stripped from observability output."""
        from omniclaude.hooks.event_registry import transform_for_observability

        payload = {
            "prompt_preview": "Fix the bug in auth.py",
            "prompt_b64": "RnVsbCBwcm9tcHQgY29udGVudA==",
            "prompt_length": 42,
            "session_id": "abc123",
        }
        result = transform_for_observability(payload)

        assert "prompt_b64" not in result
        assert "prompt_preview" in result
        assert result["prompt_length"] == 42
        assert result["session_id"] == "abc123"

    def test_transform_new_payload_preserves_prompt_length(self) -> None:
        """New payload shape: prompt_length from hook is preserved (not recalculated)."""
        from omniclaude.hooks.event_registry import transform_for_observability

        payload = {
            "prompt_preview": "Short preview",
            "prompt_b64": "TG9uZyBwcm9tcHQ=",
            "prompt_length": 500,  # Original prompt was 500 chars
            "session_id": "abc",
        }
        result = transform_for_observability(payload)

        # prompt_length should be the original value, not len(prompt_preview)
        assert result["prompt_length"] == 500

    def test_transform_new_payload_does_not_mutate_original(self) -> None:
        """New payload shape: original payload is not mutated."""
        from omniclaude.hooks.event_registry import transform_for_observability

        original = {
            "prompt_preview": "Hello",
            "prompt_b64": "SGVsbG8=",
            "prompt_length": 5,
            "session_id": "abc",
        }
        original_copy = dict(original)

        transform_for_observability(original)

        assert original == original_copy


# =============================================================================
# transform_passthrough() Tests
# =============================================================================


class TestTransformPassthrough:
    """Tests for transform_passthrough() function."""

    def test_passthrough_returns_same_payload(self) -> None:
        """Verify passthrough returns payload unchanged."""
        from omniclaude.hooks.event_registry import transform_passthrough

        payload = {"prompt": "Hello world", "session_id": "abc123"}
        result = transform_passthrough(payload)
        assert result is payload  # Same object

    def test_passthrough_preserves_all_fields(self) -> None:
        """Verify passthrough preserves all fields."""
        from omniclaude.hooks.event_registry import transform_passthrough

        payload = {
            "prompt": "Hello",
            "session_id": "abc",
            "secret": "sk-12345",
            "nested": {"key": "value"},
        }
        result = transform_passthrough(payload)
        assert result == payload

    def test_passthrough_empty_payload(self) -> None:
        """Verify passthrough handles empty payload."""
        from omniclaude.hooks.event_registry import transform_passthrough

        payload: dict[str, object] = {}
        result = transform_passthrough(payload)
        assert result == {}


# =============================================================================
# FanOutRule Tests
# =============================================================================


class TestFanOutRule:
    """Tests for FanOutRule dataclass."""

    def test_fanout_rule_creation(self) -> None:
        """Verify FanOutRule can be created."""
        from omniclaude.hooks.event_registry import FanOutRule

        rule = FanOutRule(
            topic_base=TopicBase.SESSION_STARTED,
            transform=None,
            description="Test rule",
        )
        assert rule.topic_base == TopicBase.SESSION_STARTED
        assert rule.transform is None
        assert rule.description == "Test rule"

    def test_fanout_rule_is_frozen(self) -> None:
        """Verify FanOutRule is immutable (frozen)."""
        from omniclaude.hooks.event_registry import FanOutRule

        rule = FanOutRule(
            topic_base=TopicBase.SESSION_STARTED,
            description="Test",
        )
        with pytest.raises(AttributeError):
            rule.description = "Changed"  # type: ignore[misc]

    def test_fanout_rule_apply_transform_with_none(self) -> None:
        """Verify apply_transform returns payload unchanged when transform is None."""
        from omniclaude.hooks.event_registry import FanOutRule

        rule = FanOutRule(
            topic_base=TopicBase.SESSION_STARTED,
            transform=None,
        )
        payload = {"key": "value"}
        result = rule.apply_transform(payload)
        assert result == payload  # Same content
        assert result is not payload  # Defensive copy

    def test_fanout_rule_apply_transform_with_function(self) -> None:
        """Verify apply_transform applies transform function."""
        from omniclaude.hooks.event_registry import FanOutRule

        def add_marker(payload: dict[str, object]) -> dict[str, object]:
            return {**payload, "marker": "transformed"}

        rule = FanOutRule(
            topic_base=TopicBase.SESSION_STARTED,
            transform=add_marker,
        )
        payload = {"key": "value"}
        result = rule.apply_transform(payload)
        assert result["marker"] == "transformed"
        assert result["key"] == "value"

    def test_fanout_rule_apply_transform_observability(self) -> None:
        """Verify apply_transform works with transform_for_observability."""
        from omniclaude.hooks.event_registry import (
            FanOutRule,
            transform_for_observability,
        )

        rule = FanOutRule(
            topic_base=TopicBase.PROMPT_SUBMITTED,
            transform=transform_for_observability,
            description="Sanitized preview",
        )
        payload = {"prompt": "Test prompt", "session_id": "abc"}
        result = rule.apply_transform(payload)

        assert "prompt" not in result
        assert "prompt_preview" in result
        assert "prompt_length" in result


# =============================================================================
# EventRegistration Tests
# =============================================================================


class TestEventRegistration:
    """Tests for EventRegistration dataclass."""

    def test_event_registration_creation(self) -> None:
        """Verify EventRegistration can be created."""
        from omniclaude.hooks.event_registry import EventRegistration, FanOutRule

        reg = EventRegistration(
            event_type="test.event",
            fan_out=[FanOutRule(topic_base=TopicBase.SESSION_STARTED)],
            partition_key_field="session_id",
            required_fields=["session_id"],
        )
        assert reg.event_type == "test.event"
        assert len(reg.fan_out) == 1
        assert reg.partition_key_field == "session_id"
        assert "session_id" in reg.required_fields

    def test_event_registration_is_frozen(self) -> None:
        """Verify EventRegistration is immutable (frozen)."""
        from omniclaude.hooks.event_registry import EventRegistration

        reg = EventRegistration(
            event_type="test.event",
            fan_out=[],
            required_fields=[],
        )
        with pytest.raises(AttributeError):
            reg.event_type = "changed"  # type: ignore[misc]

    def test_event_registration_default_values(self) -> None:
        """Verify EventRegistration has correct defaults."""
        from omniclaude.hooks.event_registry import EventRegistration

        reg = EventRegistration(event_type="test.event")
        assert reg.fan_out == []
        assert reg.partition_key_field is None
        assert reg.required_fields == []


# =============================================================================
# EVENT_REGISTRY Integration Tests
# =============================================================================


class TestEventRegistryIntegration:
    """Integration tests for EVENT_REGISTRY structure."""

    def test_registry_contains_all_expected_types(self) -> None:
        """Verify registry contains all expected event types."""
        from omniclaude.hooks.event_registry import EVENT_REGISTRY

        expected_types = {
            # Session events
            "session.started",
            "session.ended",
            "session.outcome",
            # Prompt events
            "prompt.submitted",
            # Tool events
            "tool.executed",
            # Routing feedback events (OMN-1892)
            "routing.feedback",
            "routing.skipped",
            # Injection tracking events (OMN-1673 INJECT-004)
            "injection.recorded",
            # Metrics events (OMN-1889)
            "context.utilization",
            "agent.match",
            "latency.breakdown",
            # Routing decision (PR-92)
            "routing.decision",
            # Notification events (OMN-1831)
            "notification.blocked",
            "notification.completed",
            # Phase metrics (OMN-2027)
            "phase.metrics",
            # Agent status (OMN-1848)
            "agent.status",
            # Pattern compliance (OMN-2263 → OMN-2256)
            "compliance.evaluate",
            # Static context change detection (OMN-2237)
            "static.context.edit.detected",
            # LLM routing observability (OMN-2273)
            "llm.routing.decision",
            "llm.routing.fallback",
            # Enrichment observability (OMN-2274)
            "context.enrichment",
            # Raw session outcome signals (OMN-2356)
            "routing.outcome.raw",
            # Shadow validation mode comparison results (OMN-2283)
            "delegation.shadow.comparison",
        }
        assert set(EVENT_REGISTRY.keys()) == expected_types

    def test_prompt_submitted_fan_out_topics(self) -> None:
        """Verify prompt.submitted fans out to correct topics."""
        from omniclaude.hooks.event_registry import EVENT_REGISTRY

        reg = EVENT_REGISTRY["prompt.submitted"]
        topic_bases = [rule.topic_base for rule in reg.fan_out]

        # Should include both intelligence and observability topics
        assert TopicBase.CLAUDE_HOOK_EVENT in topic_bases
        assert TopicBase.PROMPT_SUBMITTED in topic_bases

    def test_prompt_submitted_has_transforms(self) -> None:
        """Verify prompt.submitted has correct transforms configured."""
        from omniclaude.hooks.event_registry import (
            EVENT_REGISTRY,
            transform_for_observability,
        )

        reg = EVENT_REGISTRY["prompt.submitted"]

        # Find the observability rule
        obs_rule = None
        intel_rule = None
        for rule in reg.fan_out:
            if rule.topic_base == TopicBase.PROMPT_SUBMITTED:
                obs_rule = rule
            elif rule.topic_base == TopicBase.CLAUDE_HOOK_EVENT:
                intel_rule = rule

        assert obs_rule is not None
        assert intel_rule is not None

        # Observability should have transform
        assert obs_rule.transform == transform_for_observability

        # Intelligence should be passthrough (None)
        assert intel_rule.transform is None

    def test_session_outcome_fan_out_to_both_cmd_and_evt(self) -> None:
        """session.outcome should fan-out to both CMD (intelligence) and EVT (observability)."""
        from omniclaude.hooks.event_registry import EVENT_REGISTRY

        reg = EVENT_REGISTRY["session.outcome"]
        assert len(reg.fan_out) == 2

        topic_bases = [rule.topic_base for rule in reg.fan_out]
        assert TopicBase.SESSION_OUTCOME_CMD in topic_bases
        assert TopicBase.SESSION_OUTCOME_EVT in topic_bases

    def test_session_outcome_required_fields(self) -> None:
        """session.outcome should require session_id and outcome."""
        from omniclaude.hooks.event_registry import EVENT_REGISTRY

        reg = EVENT_REGISTRY["session.outcome"]
        assert "session_id" in reg.required_fields
        assert "outcome" in reg.required_fields

    def test_session_outcome_both_rules_are_passthrough(self) -> None:
        """session.outcome fan-out rules should both be passthrough (no transform)."""
        from omniclaude.hooks.event_registry import EVENT_REGISTRY

        reg = EVENT_REGISTRY["session.outcome"]
        for rule in reg.fan_out:
            assert rule.transform is None, (
                f"Expected passthrough for {rule.topic_base}, got transform"
            )

    def test_routing_decision_uses_onex_topic(self) -> None:
        """routing.decision should use ONEX-canonical topic, not legacy."""
        from omniclaude.hooks.event_registry import EVENT_REGISTRY

        reg = EVENT_REGISTRY["routing.decision"]
        topic_bases = [rule.topic_base for rule in reg.fan_out]
        assert TopicBase.ROUTING_DECISION in topic_bases
        # Legacy topic should NOT be present
        assert "agent-routing-decisions" not in [str(t) for t in topic_bases]

    def test_session_events_no_transform(self) -> None:
        """Verify session events use passthrough (no transform)."""
        from omniclaude.hooks.event_registry import EVENT_REGISTRY

        for event_type in ["session.started", "session.ended"]:
            reg = EVENT_REGISTRY[event_type]
            for rule in reg.fan_out:
                assert rule.transform is None

    def test_all_registrations_have_valid_structure(self) -> None:
        """Verify all registrations have valid structure."""
        from omniclaude.hooks.event_registry import (
            EVENT_REGISTRY,
            EventRegistration,
            FanOutRule,
        )

        for event_type, reg in EVENT_REGISTRY.items():
            assert isinstance(reg, EventRegistration)
            assert reg.event_type == event_type
            assert isinstance(reg.fan_out, list)
            for rule in reg.fan_out:
                assert isinstance(rule, FanOutRule)
                assert isinstance(rule.topic_base, str | TopicBase)

    def test_all_registrations_have_at_least_one_fanout(self) -> None:
        """Verify all registrations have at least one fan-out rule."""
        from omniclaude.hooks.event_registry import EVENT_REGISTRY

        for event_type, reg in EVENT_REGISTRY.items():
            assert len(reg.fan_out) >= 1, f"{event_type} has no fan-out rules"


# =============================================================================
# transform_for_observability() Edge Case Tests
# =============================================================================


class TestTransformForObservabilityEdgeCases:
    """Tests for edge cases in transform_for_observability.

    These tests specifically verify the non-string prompt handling code path
    (lines 123-124 in event_registry.py):

        if not isinstance(full_prompt, str):
            full_prompt = str(full_prompt) if full_prompt is not None else ""

    Each test verifies:
    - No exception is raised
    - `prompt_preview` is a string
    - `prompt_length` reflects the converted string length
    - Original `prompt` field is removed from output
    """

    def test_transform_handles_none_prompt(self) -> None:
        """Transform handles None prompt gracefully."""
        from omniclaude.hooks.event_registry import transform_for_observability

        payload = {"prompt": None, "session_id": "test-123"}
        result = transform_for_observability(payload)

        # Verify no exception raised (implicit)
        # Verify prompt field is removed
        assert "prompt" not in result
        # Verify prompt_preview is a string
        assert isinstance(result["prompt_preview"], str)
        assert result["prompt_preview"] == ""
        # Verify prompt_length reflects empty string
        assert result["prompt_length"] == 0
        # Verify other fields preserved
        assert result["session_id"] == "test-123"

    def test_transform_handles_integer_prompt(self) -> None:
        """Transform converts integer prompt to string."""
        from omniclaude.hooks.event_registry import transform_for_observability

        payload = {"prompt": 12345, "session_id": "test-123"}
        result = transform_for_observability(payload)

        # Verify no exception raised (implicit)
        # Verify prompt field is removed
        assert "prompt" not in result
        # Verify prompt_preview is a string
        assert isinstance(result["prompt_preview"], str)
        assert result["prompt_preview"] == "12345"
        # Verify prompt_length reflects converted string length
        assert result["prompt_length"] == 5  # len("12345")
        # Verify other fields preserved
        assert result["session_id"] == "test-123"

    def test_transform_handles_list_prompt(self) -> None:
        """Transform converts list prompt to string."""
        from omniclaude.hooks.event_registry import transform_for_observability

        payload = {"prompt": ["item1", "item2", "item3"], "session_id": "test-123"}
        result = transform_for_observability(payload)

        # Verify no exception raised (implicit)
        # Verify prompt field is removed
        assert "prompt" not in result
        # Verify prompt_preview is a string
        assert isinstance(result["prompt_preview"], str)
        # List string representation: "['item1', 'item2', 'item3']"
        expected_str = str(["item1", "item2", "item3"])
        assert result["prompt_preview"] == expected_str
        # Verify prompt_length reflects converted string length
        assert result["prompt_length"] == len(expected_str)
        # Verify other fields preserved
        assert result["session_id"] == "test-123"

    def test_transform_handles_dict_prompt(self) -> None:
        """Transform converts dict prompt to string."""
        from omniclaude.hooks.event_registry import transform_for_observability

        payload = {"prompt": {"key": "value", "num": 42}, "session_id": "test-123"}
        result = transform_for_observability(payload)

        # Verify no exception raised (implicit)
        # Verify prompt field is removed
        assert "prompt" not in result
        # Verify prompt_preview is a string
        assert isinstance(result["prompt_preview"], str)
        # Dict string representation: "{'key': 'value', 'num': 42}"
        expected_str = str({"key": "value", "num": 42})
        assert result["prompt_preview"] == expected_str
        # Verify prompt_length reflects converted string length
        assert result["prompt_length"] == len(expected_str)
        # Verify other fields preserved
        assert result["session_id"] == "test-123"

    def test_transform_handles_missing_prompt(self) -> None:
        """Transform handles payload with no prompt field."""
        from omniclaude.hooks.event_registry import transform_for_observability

        payload = {"session_id": "test-123", "other_field": "value"}
        result = transform_for_observability(payload)

        # Verify no exception raised (implicit)
        # Verify prompt field is not in result (was never there)
        assert "prompt" not in result
        # Verify prompt_preview is a string (defaults to empty)
        assert isinstance(result["prompt_preview"], str)
        assert result["prompt_preview"] == ""
        # Verify prompt_length is 0 for missing prompt
        assert result["prompt_length"] == 0
        # Verify other fields preserved
        assert result["session_id"] == "test-123"
        assert result["other_field"] == "value"

    def test_transform_handles_float_prompt(self) -> None:
        """Transform converts float prompt to string."""
        from omniclaude.hooks.event_registry import transform_for_observability

        payload = {"prompt": 3.14159, "session_id": "test-123"}
        result = transform_for_observability(payload)

        # Verify no exception raised (implicit)
        # Verify prompt field is removed
        assert "prompt" not in result
        # Verify prompt_preview is a string
        assert isinstance(result["prompt_preview"], str)
        expected_str = "3.14159"
        assert result["prompt_preview"] == expected_str
        # Verify prompt_length reflects converted string length
        assert result["prompt_length"] == len(expected_str)

    def test_transform_handles_boolean_prompt(self) -> None:
        """Transform converts boolean prompt to string."""
        from omniclaude.hooks.event_registry import transform_for_observability

        payload = {"prompt": True, "session_id": "test-123"}
        result = transform_for_observability(payload)

        # Verify no exception raised (implicit)
        # Verify prompt field is removed
        assert "prompt" not in result
        # Verify prompt_preview is a string
        assert isinstance(result["prompt_preview"], str)
        assert result["prompt_preview"] == "True"
        # Verify prompt_length reflects converted string length
        assert result["prompt_length"] == 4  # len("True")

    def test_transform_handles_nested_structure_prompt(self) -> None:
        """Transform converts nested structure prompt to string."""
        from omniclaude.hooks.event_registry import transform_for_observability

        nested = {"outer": {"inner": [1, 2, 3]}, "list": ["a", "b"]}
        payload = {"prompt": nested, "session_id": "test-123"}
        result = transform_for_observability(payload)

        # Verify no exception raised (implicit)
        # Verify prompt field is removed
        assert "prompt" not in result
        # Verify prompt_preview is a string
        assert isinstance(result["prompt_preview"], str)
        expected_str = str(nested)
        assert result["prompt_preview"] == expected_str
        # Verify prompt_length reflects converted string length
        assert result["prompt_length"] == len(expected_str)

    def test_transform_handles_zero_prompt(self) -> None:
        """Transform converts zero (falsy but valid) prompt to string."""
        from omniclaude.hooks.event_registry import transform_for_observability

        payload = {"prompt": 0, "session_id": "test-123"}
        result = transform_for_observability(payload)

        # Verify no exception raised (implicit)
        # Verify prompt field is removed
        assert "prompt" not in result
        # Verify prompt_preview is a string
        assert isinstance(result["prompt_preview"], str)
        # Zero should become "0", not empty string
        assert result["prompt_preview"] == "0"
        # Verify prompt_length reflects converted string length
        assert result["prompt_length"] == 1  # len("0")

    def test_transform_handles_empty_list_prompt(self) -> None:
        """Transform converts empty list prompt to string."""
        from omniclaude.hooks.event_registry import transform_for_observability

        payload = {"prompt": [], "session_id": "test-123"}
        result = transform_for_observability(payload)

        # Verify no exception raised (implicit)
        # Verify prompt field is removed
        assert "prompt" not in result
        # Verify prompt_preview is a string
        assert isinstance(result["prompt_preview"], str)
        assert result["prompt_preview"] == "[]"
        # Verify prompt_length reflects converted string length
        assert result["prompt_length"] == 2  # len("[]")

    def test_transform_handles_empty_dict_prompt(self) -> None:
        """Transform converts empty dict prompt to string."""
        from omniclaude.hooks.event_registry import transform_for_observability

        payload = {"prompt": {}, "session_id": "test-123"}
        result = transform_for_observability(payload)

        # Verify no exception raised (implicit)
        # Verify prompt field is removed
        assert "prompt" not in result
        # Verify prompt_preview is a string
        assert isinstance(result["prompt_preview"], str)
        assert result["prompt_preview"] == "{}"
        # Verify prompt_length reflects converted string length
        assert result["prompt_length"] == 2  # len("{}")
