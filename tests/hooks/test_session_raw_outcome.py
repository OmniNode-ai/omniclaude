# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Unit tests for routing feedback session outcome handling.

OMN-2622: ModelSessionRawOutcomePayload and routing.outcome.raw topic are deprecated.
All routing feedback (produced and skipped) is now emitted on routing-feedback.v1 via
ModelRoutingFeedbackPayload with a ``feedback_status`` field.

Remaining in this file:
- build_session_raw_outcome_event helper (pure Python, used internally for accumulator logic)
- TestBuildSessionEndEvent: Acceptance tests from OMN-2356 DoD (helper logic still valid)
- TestSessionAccumulatorFileFormat: Session accumulator JSON round-trip tests
- TestRoutingFeedbackSchema: Replaces TestSessionRawOutcomeSchema — validates new schema

Removed (OMN-2622):
- TestSessionRawOutcomeSchema: tests for ModelSessionRawOutcomePayload (removed)
- TestRoutingOutcomeRawRegistry: tests for routing.outcome.raw registry entry (tombstoned)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

pytestmark = pytest.mark.unit


# =============================================================================
# Helpers: build_session_raw_outcome_event
# This mirrors accumulator-reading logic in session-end.sh.
# Pure function — no I/O, no datetime.now().
# =============================================================================


def build_session_raw_outcome_event(
    session_id: str,
    session_state: dict[str, Any],
    tool_calls_count: int = 0,
    duration_ms: int = 0,
) -> dict[str, Any]:
    """Build the raw session outcome event payload from observable facts.

    Args:
        session_id: Session identifier.
        session_state: Contents of /tmp/omniclaude-session-{session_id}.json,
            or {} if the file does not exist (no UserPromptSubmit in session).
        tool_calls_count: Tool calls from Claude's SessionEnd payload.
        duration_ms: Session duration from Claude's SessionEnd payload.

    Returns:
        Dict with raw session observable facts.
        Intentionally excludes utilization_score and agent_match_score —
        those are derived values belonging in omniintelligence.
    """
    injection_occurred: bool = bool(session_state.get("injection_occurred", False))
    patterns_injected_count: int = int(session_state.get("patterns_injected_count", 0))
    agent_selected: str = str(session_state.get("agent_selected", ""))
    routing_confidence: float = float(session_state.get("routing_confidence", 0.0))

    return {
        "session_id": session_id,
        "injection_occurred": injection_occurred,
        "patterns_injected_count": patterns_injected_count,
        "tool_calls_count": tool_calls_count,
        "duration_ms": duration_ms,
        "agent_selected": agent_selected,
        "routing_confidence": routing_confidence,
    }


# =============================================================================
# Test: New schema — ModelRoutingFeedbackPayload with feedback_status (OMN-2622)
# =============================================================================


class TestRoutingFeedbackSchema:
    """Verify ModelRoutingFeedbackPayload schema with OMN-2622 feedback_status field."""

    def test_schema_contains_feedback_status_and_skip_reason(self) -> None:
        """ModelRoutingFeedbackPayload must include feedback_status and skip_reason."""
        pytest.importorskip(
            "tiktoken", reason="requires tiktoken for omniclaude.hooks import chain"
        )
        from omniclaude.hooks.schemas import ModelRoutingFeedbackPayload

        field_names = set(ModelRoutingFeedbackPayload.model_fields.keys())
        assert "feedback_status" in field_names, (
            "feedback_status must be present [OMN-2622]"
        )
        assert "skip_reason" in field_names, "skip_reason must be present [OMN-2622]"
        assert "outcome" in field_names, "outcome must be present"
        assert "session_id" in field_names, "session_id must be present"
        assert "emitted_at" in field_names, "emitted_at must be present"

    def test_schema_is_frozen(self) -> None:
        """ModelRoutingFeedbackPayload must be frozen (immutable after construction)."""
        pytest.importorskip(
            "tiktoken", reason="requires tiktoken for omniclaude.hooks import chain"
        )
        from omniclaude.hooks.schemas import ModelRoutingFeedbackPayload

        now = datetime(2026, 2, 28, 12, 0, 0, tzinfo=UTC)
        event = ModelRoutingFeedbackPayload(
            session_id="abc12345-1234-5678-abcd-1234567890ab",
            outcome="success",
            feedback_status="produced",
            skip_reason=None,
            emitted_at=now,
        )
        with pytest.raises(Exception):
            event.session_id = "other"  # type: ignore[misc]

    def test_produced_event_constructs_with_realistic_values(self) -> None:
        """Schema accepts realistic produced session values."""
        pytest.importorskip(
            "tiktoken", reason="requires tiktoken for omniclaude.hooks import chain"
        )
        from omniclaude.hooks.schemas import ModelRoutingFeedbackPayload

        now = datetime(2026, 2, 28, 12, 0, 0, tzinfo=UTC)
        event = ModelRoutingFeedbackPayload(
            session_id="abc12345-1234-5678-abcd-1234567890ab",
            outcome="success",
            feedback_status="produced",
            skip_reason=None,
            emitted_at=now,
        )
        assert event.session_id == "abc12345-1234-5678-abcd-1234567890ab"
        assert event.outcome == "success"
        assert event.feedback_status == "produced"
        assert event.skip_reason is None
        assert event.emitted_at == now

    def test_skipped_event_constructs_with_skip_reason(self) -> None:
        """Schema accepts skipped events with a skip_reason."""
        pytest.importorskip(
            "tiktoken", reason="requires tiktoken for omniclaude.hooks import chain"
        )
        from omniclaude.hooks.schemas import ModelRoutingFeedbackPayload

        now = datetime(2026, 2, 28, 12, 0, 0, tzinfo=UTC)
        event = ModelRoutingFeedbackPayload(
            session_id="abc12345-1234-5678-abcd-1234567890ab",
            outcome="unknown",
            feedback_status="skipped",
            skip_reason="NO_INJECTION",
            emitted_at=now,
        )
        assert event.feedback_status == "skipped"
        assert event.skip_reason == "NO_INJECTION"

    def test_event_name_discriminator(self) -> None:
        """event_name must be 'routing.feedback' for polymorphic deserialization."""
        pytest.importorskip(
            "tiktoken", reason="requires tiktoken for omniclaude.hooks import chain"
        )
        from omniclaude.hooks.schemas import ModelRoutingFeedbackPayload

        now = datetime(2026, 2, 28, 12, 0, 0, tzinfo=UTC)
        event = ModelRoutingFeedbackPayload(
            session_id="abc12345-1234-5678-abcd-1234567890ab",
            outcome="success",
            feedback_status="produced",
            skip_reason=None,
            emitted_at=now,
        )
        assert event.event_name == "routing.feedback"

    def test_routing_outcome_raw_tombstoned(self) -> None:
        """routing.outcome.raw must NOT be in EVENT_REGISTRY (tombstoned OMN-2622)."""
        pytest.importorskip(
            "tiktoken", reason="requires tiktoken for omniclaude.hooks import chain"
        )
        from omniclaude.hooks.event_registry import EVENT_REGISTRY

        assert "routing.outcome.raw" not in EVENT_REGISTRY, (
            "routing.outcome.raw was tombstoned in OMN-2622 — must not be in EVENT_REGISTRY"
        )

    def test_routing_skipped_tombstoned(self) -> None:
        """routing.skipped must NOT be in EVENT_REGISTRY (tombstoned OMN-2622)."""
        pytest.importorskip(
            "tiktoken", reason="requires tiktoken for omniclaude.hooks import chain"
        )
        from omniclaude.hooks.event_registry import EVENT_REGISTRY

        assert "routing.skipped" not in EVENT_REGISTRY, (
            "routing.skipped was tombstoned in OMN-2622 — must not be in EVENT_REGISTRY"
        )


# =============================================================================
# Test: Acceptance tests from ticket DoD
# =============================================================================


class TestBuildSessionEndEvent:
    """Acceptance tests from OMN-2356 DoD."""

    def test_session_end_event_does_not_contain_derived_scores(self) -> None:
        """Derived scores belong in omniintelligence, not the hook payload."""
        mock_session_state = {
            "injection_occurred": True,
            "patterns_injected_count": 3,
            "agent_selected": "omniarchon",
            "routing_confidence": 0.91,
        }
        event = build_session_raw_outcome_event(
            session_id="abc12345-1234-5678-abcd-1234567890ab",
            session_state=mock_session_state,
            tool_calls_count=12,
            duration_ms=45200,
        )
        assert "utilization_score" not in event, (
            "Derived scores belong in omniintelligence"
        )
        assert "agent_match_score" not in event, (
            "Derived scores belong in omniintelligence"
        )
        assert event["patterns_injected_count"] >= 0
        assert event["tool_calls_count"] >= 0

    def test_session_end_event_uses_real_injection_state(self) -> None:
        """Real injection state (True) propagates into event."""
        session_state = {
            "injection_occurred": True,
            "patterns_injected_count": 5,
            "agent_selected": "agent-api-architect",
            "routing_confidence": 0.85,
        }
        event = build_session_raw_outcome_event(
            session_id="abc12345-1234-5678-abcd-1234567890ab",
            session_state=session_state,
            tool_calls_count=20,
            duration_ms=30000,
        )
        assert event["injection_occurred"] is True
        assert event["patterns_injected_count"] == 5
        assert event["agent_selected"] == "agent-api-architect"
        assert abs(event["routing_confidence"] - 0.85) < 1e-9

    def test_session_end_event_with_missing_accumulator(self) -> None:
        """Missing session state (no UserPromptSubmit) produces safe defaults."""
        event = build_session_raw_outcome_event(
            session_id="abc12345-1234-5678-abcd-1234567890ab",
            session_state={},  # File not found → empty dict
            tool_calls_count=0,
            duration_ms=5000,
        )
        assert event["injection_occurred"] is False
        assert event["patterns_injected_count"] == 0
        assert event["agent_selected"] == ""
        assert event["routing_confidence"] == 0.0
        assert event["tool_calls_count"] == 0

    def test_tool_calls_count_comes_from_claude_payload(self) -> None:
        """tool_calls_count comes from Claude's SessionEnd payload, not session accumulator."""
        session_state = {
            "injection_occurred": True,
            "patterns_injected_count": 2,
            "agent_selected": "agent-testing",
            "routing_confidence": 0.75,
        }
        event = build_session_raw_outcome_event(
            session_id="abc12345-1234-5678-abcd-1234567890ab",
            session_state=session_state,
            tool_calls_count=42,  # From Claude's SessionEnd payload
            duration_ms=60000,
        )
        assert event["tool_calls_count"] == 42

    def test_duration_ms_comes_from_claude_payload(self) -> None:
        """duration_ms comes from Claude's SessionEnd payload (durationMs field)."""
        session_state = {}
        event = build_session_raw_outcome_event(
            session_id="abc12345-1234-5678-abcd-1234567890ab",
            session_state=session_state,
            tool_calls_count=0,
            duration_ms=120000,  # From Claude's SessionEnd payload
        )
        assert event["duration_ms"] == 120000


# =============================================================================
# Test: JSON round-trip (session accumulator file format)
# =============================================================================


class TestSessionAccumulatorFileFormat:
    """Verify the session accumulator JSON written by user-prompt-submit.sh."""

    def test_accumulator_json_is_parseable(self) -> None:
        """Session accumulator must be valid JSON readable by jq."""
        accumulator = {
            "injection_occurred": True,
            "patterns_injected_count": 3,
            "agent_selected": "omniarchon",
            "routing_confidence": 0.91,
        }
        raw_json = json.dumps(accumulator)
        parsed = json.loads(raw_json)

        assert parsed["injection_occurred"] is True
        assert parsed["patterns_injected_count"] == 3
        assert parsed["agent_selected"] == "omniarchon"
        assert abs(parsed["routing_confidence"] - 0.91) < 1e-9

    def test_accumulator_with_no_injection(self) -> None:
        """No injection → injection_occurred=False, patterns_injected_count=0."""
        accumulator = {
            "injection_occurred": False,
            "patterns_injected_count": 0,
            "agent_selected": "",
            "routing_confidence": 0.0,
        }
        event = build_session_raw_outcome_event(
            session_id="test-session-id",
            session_state=accumulator,
            tool_calls_count=0,
            duration_ms=0,
        )
        assert event["injection_occurred"] is False
        assert event["patterns_injected_count"] == 0

    def test_accumulator_ignores_extra_fields(self) -> None:
        """Extra fields in accumulator are silently ignored (forward compat)."""
        accumulator = {
            "injection_occurred": True,
            "patterns_injected_count": 1,
            "agent_selected": "agent-debug",
            "routing_confidence": 0.6,
            "future_extra_field": "should_be_ignored",
        }
        event = build_session_raw_outcome_event(
            session_id="test-session-id",
            session_state=accumulator,
            tool_calls_count=5,
            duration_ms=10000,
        )
        # Extra field must not be in event payload
        assert "future_extra_field" not in event

    def test_accumulator_false_injection_with_nonzero_count(self) -> None:
        """If injection_occurred=False and patterns_injected_count > 0,
        injection_occurred governs the event (data consistency enforced by hook).
        """
        accumulator = {
            "injection_occurred": False,
            "patterns_injected_count": 5,  # Inconsistent — hook wrote false
            "agent_selected": "",
            "routing_confidence": 0.0,
        }
        event = build_session_raw_outcome_event(
            session_id="test-session-id",
            session_state=accumulator,
        )
        # injection_occurred=False takes precedence (as written by hook)
        assert event["injection_occurred"] is False

    def test_accumulator_with_nonnumeric_pattern_count_defaults_to_zero(self) -> None:
        """Documents the Python-side and shell-side behavior for a non-numeric
        patterns_injected_count value.

        Part (a) — Python-side behavior:
          build_session_raw_outcome_event uses bare int() with no try/except.
          Passing "not-a-number" directly raises ValueError.  This documents
          that the helper does NOT silently coerce bad input.

        Part (b) — Shell-side guard behavior:
          user-prompt-submit.sh guards with:
            [[ PATTERN_COUNT =~ ^[0-9]+$ ]] || PATTERN_COUNT=0
          After that coercion the helper receives a valid integer and succeeds.
          This part verifies the post-coercion path produces the expected result.
        """
        accumulator_with_bad_count: dict[str, Any] = {
            "injection_occurred": True,
            "patterns_injected_count": "not-a-number",  # malformed
            "agent_selected": "agent-api-architect",
            "routing_confidence": 0.85,
        }

        # Part (a): helper raises ValueError on non-numeric input — no silent coercion.
        with pytest.raises(ValueError):
            build_session_raw_outcome_event(
                session_id="abc12345-1234-5678-abcd-1234567890ab",
                session_state=accumulator_with_bad_count,
                tool_calls_count=5,
                duration_ms=10000,
            )

        # Part (b): after the shell-side guard coerces the bad value to 0,
        # the helper succeeds and the event reflects the coerced count.
        safe_state = dict(accumulator_with_bad_count)
        safe_state["patterns_injected_count"] = int(
            "0"
        )  # mirrors shell: PATTERN_COUNT=0

        event = build_session_raw_outcome_event(
            session_id="abc12345-1234-5678-abcd-1234567890ab",
            session_state=safe_state,
            tool_calls_count=5,
            duration_ms=10000,
        )
        assert event["patterns_injected_count"] == 0, (
            "After shell-side coercion to 0, patterns_injected_count must be 0"
        )
        # injection_occurred=True is preserved — the count coercion is independent
        assert event["injection_occurred"] is True

    def test_multi_prompt_accumulator_not_overwritten(self) -> None:
        """Regression: SESSION_ALREADY_INJECTED=true on subsequent prompts must not
        overwrite the first-prompt injection_occurred=true value with false.

        user-prompt-submit.sh guards against this by only writing the accumulator
        when the file does not yet exist (! -f $_ACCUM_FILE).  This test verifies
        the Python helper preserves the first-prompt state when it is passed in
        as session_state — i.e. the accumulator file content is used as-is, with
        no further mutation for subsequent prompts.

        Scenario:
          Prompt 1 → injection_occurred=True, patterns=3 written to accumulator.
          Prompt 2 → SESSION_ALREADY_INJECTED=true → accumulator file already exists,
                     write is skipped in the shell script.
          session-end.sh reads accumulator → must see injection_occurred=True (prompt 1).
        """
        # Accumulator as written by the FIRST prompt (injection succeeded)
        first_prompt_accumulator = {
            "injection_occurred": True,
            "patterns_injected_count": 3,
            "agent_selected": "agent-api-architect",
            "routing_confidence": 0.85,
        }

        # Build event from the accumulator that session-end reads (unchanged from prompt 1)
        event = build_session_raw_outcome_event(
            session_id="abc12345-1234-5678-abcd-1234567890ab",
            session_state=first_prompt_accumulator,
            tool_calls_count=10,
            duration_ms=60000,
        )

        # The first-prompt injection state must be preserved — NOT overwritten with false
        assert event["injection_occurred"] is True, (
            "Multi-prompt regression: injection_occurred must preserve the first-prompt "
            "value (True), not be overwritten by a subsequent prompt's SESSION_ALREADY_INJECTED=true path"
        )
        assert event["patterns_injected_count"] == 3, (
            "patterns_injected_count from first prompt must be preserved"
        )
        assert event["agent_selected"] == "agent-api-architect", (
            "agent_selected from first prompt must be preserved"
        )
        assert abs(event["routing_confidence"] - 0.85) < 1e-9, (
            "routing_confidence from first prompt must be preserved"
        )
