# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Unit tests for session raw outcome event (OMN-2356).

Verifies:
- ModelSessionRawOutcomePayload schema shape (no derived scores)
- build_session_raw_outcome_event helper (used by session-end.sh logic)
- routing.outcome.raw event type is registered in EVENT_REGISTRY
- ROUTING_OUTCOME_RAW topic exists in TopicBase
- Acceptance tests from ticket DoD

Part of OMN-2356: Emit raw outcome signals instead of hardcoded/zero derived scores.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

pytestmark = pytest.mark.unit


# =============================================================================
# Helpers: build_session_raw_outcome_event
# This mirrors the logic in session-end.sh to produce the raw payload dict.
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
        Dict matching ModelSessionRawOutcomePayload (minus emitted_at).
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
# Test: Schema shape — no derived scores
# =============================================================================


class TestSessionRawOutcomeSchema:
    """Verify ModelSessionRawOutcomePayload has correct shape."""

    def test_schema_does_not_contain_derived_scores(self) -> None:
        """Derived scores (utilization_score, agent_match_score) must not be in schema."""
        pytest.importorskip(
            "tiktoken", reason="requires tiktoken for omniclaude.hooks import chain"
        )
        from omniclaude.hooks.schemas import ModelSessionRawOutcomePayload

        # Verify the model fields do not include derived metrics
        field_names = set(ModelSessionRawOutcomePayload.model_fields.keys())
        assert "utilization_score" not in field_names, (
            "utilization_score is a derived score — belongs in omniintelligence, not the hook"
        )
        assert "agent_match_score" not in field_names, (
            "agent_match_score is a derived score — belongs in omniintelligence, not the hook"
        )

    def test_schema_contains_required_raw_fields(self) -> None:
        """Raw signal fields must be present."""
        pytest.importorskip(
            "tiktoken", reason="requires tiktoken for omniclaude.hooks import chain"
        )
        from omniclaude.hooks.schemas import ModelSessionRawOutcomePayload

        field_names = set(ModelSessionRawOutcomePayload.model_fields.keys())
        for required in [
            "session_id",
            "injection_occurred",
            "patterns_injected_count",
            "tool_calls_count",
            "duration_ms",
            "agent_selected",
            "routing_confidence",
            "emitted_at",
        ]:
            assert required in field_names, f"Expected field {required!r} in schema"

    def test_schema_is_frozen(self) -> None:
        """ModelSessionRawOutcomePayload must be frozen (immutable after construction)."""
        pytest.importorskip(
            "tiktoken", reason="requires tiktoken for omniclaude.hooks import chain"
        )
        from omniclaude.hooks.schemas import ModelSessionRawOutcomePayload

        now = datetime(2026, 2, 19, 12, 0, 0, tzinfo=UTC)
        event = ModelSessionRawOutcomePayload(
            session_id="abc12345-1234-5678-abcd-1234567890ab",
            injection_occurred=True,
            patterns_injected_count=3,
            tool_calls_count=12,
            duration_ms=45200,
            emitted_at=now,
        )
        with pytest.raises(Exception):
            event.session_id = "other"  # type: ignore[misc]

    def test_schema_constructs_with_realistic_values(self) -> None:
        """Schema accepts realistic session-end values."""
        pytest.importorskip(
            "tiktoken", reason="requires tiktoken for omniclaude.hooks import chain"
        )
        from omniclaude.hooks.schemas import ModelSessionRawOutcomePayload

        now = datetime(2026, 2, 19, 12, 0, 0, tzinfo=UTC)
        event = ModelSessionRawOutcomePayload(
            session_id="abc12345-1234-5678-abcd-1234567890ab",
            injection_occurred=True,
            patterns_injected_count=3,
            tool_calls_count=12,
            duration_ms=45200,
            agent_selected="omniarchon",
            routing_confidence=0.91,
            emitted_at=now,
        )
        assert event.session_id == "abc12345-1234-5678-abcd-1234567890ab"
        assert event.injection_occurred is True
        assert event.patterns_injected_count == 3
        assert event.tool_calls_count == 12
        assert event.duration_ms == 45200
        assert event.agent_selected == "omniarchon"
        assert abs(event.routing_confidence - 0.91) < 1e-9
        assert event.emitted_at == now

    def test_schema_constructs_with_zero_injection(self) -> None:
        """Schema accepts a session with no injection (injection_occurred=False)."""
        pytest.importorskip(
            "tiktoken", reason="requires tiktoken for omniclaude.hooks import chain"
        )
        from omniclaude.hooks.schemas import ModelSessionRawOutcomePayload

        now = datetime(2026, 2, 19, 12, 0, 0, tzinfo=UTC)
        event = ModelSessionRawOutcomePayload(
            session_id="abc12345-1234-5678-abcd-1234567890ab",
            injection_occurred=False,
            patterns_injected_count=0,
            tool_calls_count=0,
            duration_ms=0,
            emitted_at=now,
        )
        assert event.injection_occurred is False
        assert event.patterns_injected_count == 0
        assert event.agent_selected == ""
        assert event.routing_confidence == 0.0

    def test_routing_confidence_above_one_raises_validation_error(self) -> None:
        """routing_confidence > 1.0 must be rejected (ge=0.0, le=1.0 constraint)."""
        pytest.importorskip(
            "tiktoken", reason="requires tiktoken for omniclaude.hooks import chain"
        )
        from pydantic import ValidationError

        from omniclaude.hooks.schemas import ModelSessionRawOutcomePayload

        now = datetime(2026, 2, 19, 12, 0, 0, tzinfo=UTC)
        with pytest.raises(ValidationError):
            ModelSessionRawOutcomePayload(
                session_id="abc12345-1234-5678-abcd-1234567890ab",
                injection_occurred=False,
                patterns_injected_count=0,
                tool_calls_count=0,
                duration_ms=0,
                routing_confidence=1.1,
                emitted_at=now,
            )

    def test_routing_confidence_below_zero_raises_validation_error(self) -> None:
        """routing_confidence < 0.0 must be rejected (ge=0.0, le=1.0 constraint)."""
        pytest.importorskip(
            "tiktoken", reason="requires tiktoken for omniclaude.hooks import chain"
        )
        from pydantic import ValidationError

        from omniclaude.hooks.schemas import ModelSessionRawOutcomePayload

        now = datetime(2026, 2, 19, 12, 0, 0, tzinfo=UTC)
        with pytest.raises(ValidationError):
            ModelSessionRawOutcomePayload(
                session_id="abc12345-1234-5678-abcd-1234567890ab",
                injection_occurred=False,
                patterns_injected_count=0,
                tool_calls_count=0,
                duration_ms=0,
                routing_confidence=-0.1,
                emitted_at=now,
            )

    def test_event_name_discriminator(self) -> None:
        """event_name must be 'routing.outcome.raw' for polymorphic deserialization."""
        pytest.importorskip(
            "tiktoken", reason="requires tiktoken for omniclaude.hooks import chain"
        )
        from omniclaude.hooks.schemas import ModelSessionRawOutcomePayload

        now = datetime(2026, 2, 19, 12, 0, 0, tzinfo=UTC)
        event = ModelSessionRawOutcomePayload(
            session_id="abc12345-1234-5678-abcd-1234567890ab",
            injection_occurred=False,
            patterns_injected_count=0,
            tool_calls_count=0,
            duration_ms=0,
            emitted_at=now,
        )
        assert event.event_name == "routing.outcome.raw"


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
# Test: Event registry
# =============================================================================


class TestRoutingOutcomeRawRegistry:
    """Verify routing.outcome.raw is registered correctly in EVENT_REGISTRY."""

    def test_routing_outcome_raw_is_registered(self) -> None:
        """routing.outcome.raw must be in EVENT_REGISTRY."""
        pytest.importorskip(
            "tiktoken", reason="requires tiktoken for omniclaude.hooks import chain"
        )
        from omniclaude.hooks.event_registry import EVENT_REGISTRY

        assert "routing.outcome.raw" in EVENT_REGISTRY, (
            "routing.outcome.raw must be registered in EVENT_REGISTRY"
        )

    def test_routing_outcome_raw_has_correct_required_fields(self) -> None:
        """routing.outcome.raw required_fields must include key raw signal fields."""
        pytest.importorskip(
            "tiktoken", reason="requires tiktoken for omniclaude.hooks import chain"
        )
        from omniclaude.hooks.event_registry import EVENT_REGISTRY

        reg = EVENT_REGISTRY["routing.outcome.raw"]
        required = set(reg.required_fields)
        assert "session_id" in required
        assert "injection_occurred" in required
        assert "tool_calls_count" in required
        assert "duration_ms" in required

    def test_routing_outcome_raw_targets_correct_topic(self) -> None:
        """routing.outcome.raw must fan-out to ROUTING_OUTCOME_RAW topic."""
        pytest.importorskip(
            "tiktoken", reason="requires tiktoken for omniclaude.hooks import chain"
        )
        from omniclaude.hooks.event_registry import EVENT_REGISTRY
        from omniclaude.hooks.topics import TopicBase

        reg = EVENT_REGISTRY["routing.outcome.raw"]
        assert len(reg.fan_out) == 1
        assert reg.fan_out[0].topic_base == TopicBase.ROUTING_OUTCOME_RAW

    def test_routing_outcome_raw_topic_value(self) -> None:
        """ROUTING_OUTCOME_RAW topic must follow ONEX canonical naming."""
        pytest.importorskip(
            "tiktoken", reason="requires tiktoken for omniclaude.hooks import chain"
        )
        from omniclaude.hooks.topics import TopicBase

        topic = TopicBase.ROUTING_OUTCOME_RAW
        assert topic.startswith("onex.evt.omniclaude."), (
            "Topic must be an evt (observability) topic under omniclaude producer"
        )
        assert "routing-outcome-raw" in topic

    def test_routing_outcome_raw_no_derived_scores_in_required_fields(self) -> None:
        """Derived scores must not appear in required_fields for routing.outcome.raw."""
        pytest.importorskip(
            "tiktoken", reason="requires tiktoken for omniclaude.hooks import chain"
        )
        from omniclaude.hooks.event_registry import EVENT_REGISTRY

        reg = EVENT_REGISTRY["routing.outcome.raw"]
        required = set(reg.required_fields)
        assert "utilization_score" not in required, (
            "utilization_score is derived — must not be in required_fields"
        )
        assert "agent_match_score" not in required, (
            "agent_match_score is derived — must not be in required_fields"
        )


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
