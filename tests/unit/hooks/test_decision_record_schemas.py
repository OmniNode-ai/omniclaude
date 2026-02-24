# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Tests for DecisionRecord Kafka topics and event envelope schemas (OMN-2465).

Validates:
- Topic names follow ONEX canonical format
- Envelope schema is frozen with explicit timestamp (no default)
- Privacy split: evt payload never leaks sensitive fields (rationale, snapshot)
- Schema passes type validation
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from omniclaude.hooks.schemas import (
    ModelHookDecisionRecordedPayload,
)
from omniclaude.hooks.topics import TopicBase

# All tests in this module are unit tests
pytestmark = pytest.mark.unit


# =============================================================================
# Helper factories
# =============================================================================


def make_valid_payload(**overrides) -> ModelHookDecisionRecordedPayload:
    """Build a valid ModelHookDecisionRecordedPayload with sensible defaults."""
    defaults = {
        "decision_id": "dec-abc123",
        "decision_type": "agent_routing",
        "selected_candidate": "polymorphic-agent",
        "candidates_count": 5,
        "has_rationale": True,
        "emitted_at": datetime(2026, 2, 21, 12, 0, 0, tzinfo=UTC),
        "session_id": "session-xyz",
    }
    defaults.update(overrides)
    return ModelHookDecisionRecordedPayload(**defaults)


# =============================================================================
# R1: Topic names follow canonical ONEX format
# =============================================================================


class TestDecisionRecordTopics:
    """R1 — Topic entries exist in TopicBase and follow ONEX naming convention."""

    def test_evt_topic_exists_in_topicbase(self) -> None:
        """DECISION_RECORDED_EVT must be present in TopicBase enum."""
        assert hasattr(TopicBase, "DECISION_RECORDED_EVT")

    def test_cmd_topic_exists_in_topicbase(self) -> None:
        """DECISION_RECORDED_CMD must be present in TopicBase enum."""
        assert hasattr(TopicBase, "DECISION_RECORDED_CMD")

    def test_evt_topic_value(self) -> None:
        """EVT topic must be exactly 'onex.evt.omniintelligence.decision-recorded.v1'."""
        assert (
            TopicBase.DECISION_RECORDED_EVT
            == "onex.evt.omniintelligence.decision-recorded.v1"
        )

    def test_cmd_topic_value(self) -> None:
        """CMD topic must be exactly 'onex.cmd.omniintelligence.decision-recorded.v1'."""
        assert (
            TopicBase.DECISION_RECORDED_CMD
            == "onex.cmd.omniintelligence.decision-recorded.v1"
        )

    def test_evt_topic_follows_onex_naming(self) -> None:
        """EVT topic must start with 'onex.evt.' and end with '.v1'."""
        topic = TopicBase.DECISION_RECORDED_EVT
        assert topic.startswith("onex.evt."), f"Expected evt topic, got: {topic}"
        assert topic.endswith(".v1"), f"Expected versioned topic, got: {topic}"

    def test_cmd_topic_follows_onex_naming(self) -> None:
        """CMD topic must start with 'onex.cmd.' and end with '.v1'."""
        topic = TopicBase.DECISION_RECORDED_CMD
        assert topic.startswith("onex.cmd."), f"Expected cmd topic, got: {topic}"
        assert topic.endswith(".v1"), f"Expected versioned topic, got: {topic}"

    def test_topics_are_distinct(self) -> None:
        """EVT and CMD topics must have different string values."""
        assert TopicBase.DECISION_RECORDED_EVT != TopicBase.DECISION_RECORDED_CMD

    def test_topics_share_event_name(self) -> None:
        """Both topics must carry the 'decision-recorded' event name segment."""
        assert "decision-recorded" in TopicBase.DECISION_RECORDED_EVT
        assert "decision-recorded" in TopicBase.DECISION_RECORDED_CMD

    def test_topics_producer_is_omniintelligence(self) -> None:
        """Both topics must use 'omniintelligence' as the producer segment."""
        assert "omniintelligence" in TopicBase.DECISION_RECORDED_EVT
        assert "omniintelligence" in TopicBase.DECISION_RECORDED_CMD


# =============================================================================
# R2: Envelope schema is frozen with explicit timestamp
# =============================================================================


class TestDecisionRecordedPayloadSchema:
    """R2 — ModelHookDecisionRecordedPayload frozen schema contract."""

    def test_valid_payload_constructs(self) -> None:
        """Valid payload must construct without error."""
        payload = make_valid_payload()
        assert payload.decision_id == "dec-abc123"
        assert payload.decision_type == "agent_routing"
        assert payload.selected_candidate == "polymorphic-agent"
        assert payload.candidates_count == 5
        assert payload.has_rationale is True
        assert payload.session_id == "session-xyz"

    def test_emitted_at_is_required(self) -> None:
        """emitted_at must be required — no default value."""
        with pytest.raises(ValidationError) as exc_info:
            ModelHookDecisionRecordedPayload(  # type: ignore[call-arg]
                decision_id="dec-abc123",
                decision_type="agent_routing",
                selected_candidate="polymorphic-agent",
                candidates_count=3,
                has_rationale=False,
                # emitted_at intentionally omitted
            )
        errors = exc_info.value.errors()
        field_names = [e["loc"][0] for e in errors]
        assert "emitted_at" in field_names

    def test_emitted_at_timezone_aware(self) -> None:
        """emitted_at must be timezone-aware."""
        payload = make_valid_payload(
            emitted_at=datetime(2026, 2, 21, 12, 0, 0, tzinfo=UTC)
        )
        assert payload.emitted_at.tzinfo is not None

    def test_schema_is_frozen(self) -> None:
        """Frozen schema must reject attribute mutation."""
        payload = make_valid_payload()
        with pytest.raises((TypeError, ValidationError)):
            payload.decision_id = "mutated"  # type: ignore[misc]

    def test_extra_fields_ignored(self) -> None:
        """Extra fields must be silently ignored (extra='ignore')."""
        payload = ModelHookDecisionRecordedPayload(
            decision_id="dec-001",
            decision_type="agent_routing",
            selected_candidate="api-architect",
            candidates_count=2,
            has_rationale=False,
            emitted_at=datetime(2026, 2, 21, 12, 0, 0, tzinfo=UTC),
            agent_rationale="this is sensitive and must be ignored",  # type: ignore[call-arg]
            reproducibility_snapshot={"foo": "bar"},  # type: ignore[call-arg]
        )
        # Sensitive extra fields must not be present on the model
        assert not hasattr(payload, "agent_rationale")
        assert not hasattr(payload, "reproducibility_snapshot")

    def test_from_attributes_enabled(self) -> None:
        """Model must support from_attributes=True for ORM compatibility."""
        config = ModelHookDecisionRecordedPayload.model_config
        assert config.get("from_attributes") is True

    def test_session_id_optional(self) -> None:
        """session_id must default to None when omitted."""
        payload = make_valid_payload(session_id=None)
        assert payload.session_id is None

    def test_session_id_none_by_default(self) -> None:
        """session_id field must be optional (None default)."""
        payload = ModelHookDecisionRecordedPayload(
            decision_id="dec-no-session",
            decision_type="plan_selection",
            selected_candidate="plan-a",
            candidates_count=1,
            has_rationale=False,
            emitted_at=datetime(2026, 2, 21, 9, 0, 0, tzinfo=UTC),
        )
        assert payload.session_id is None

    def test_decision_id_required(self) -> None:
        """decision_id must be required."""
        with pytest.raises(ValidationError) as exc_info:
            ModelHookDecisionRecordedPayload(  # type: ignore[call-arg]
                decision_type="agent_routing",
                selected_candidate="polymorphic-agent",
                candidates_count=1,
                has_rationale=False,
                emitted_at=datetime(2026, 2, 21, 12, 0, 0, tzinfo=UTC),
            )
        errors = exc_info.value.errors()
        field_names = [e["loc"][0] for e in errors]
        assert "decision_id" in field_names

    def test_decision_id_cannot_be_empty(self) -> None:
        """decision_id must be non-empty (min_length=1)."""
        with pytest.raises(ValidationError):
            make_valid_payload(decision_id="")

    def test_decision_type_required(self) -> None:
        """decision_type must be required."""
        with pytest.raises(ValidationError) as exc_info:
            ModelHookDecisionRecordedPayload(  # type: ignore[call-arg]
                decision_id="dec-001",
                selected_candidate="polymorphic-agent",
                candidates_count=1,
                has_rationale=False,
                emitted_at=datetime(2026, 2, 21, 12, 0, 0, tzinfo=UTC),
            )
        errors = exc_info.value.errors()
        field_names = [e["loc"][0] for e in errors]
        assert "decision_type" in field_names

    def test_selected_candidate_required(self) -> None:
        """selected_candidate must be required."""
        with pytest.raises(ValidationError) as exc_info:
            ModelHookDecisionRecordedPayload(  # type: ignore[call-arg]
                decision_id="dec-001",
                decision_type="agent_routing",
                candidates_count=1,
                has_rationale=False,
                emitted_at=datetime(2026, 2, 21, 12, 0, 0, tzinfo=UTC),
            )
        errors = exc_info.value.errors()
        field_names = [e["loc"][0] for e in errors]
        assert "selected_candidate" in field_names

    def test_candidates_count_non_negative(self) -> None:
        """candidates_count must be >= 0."""
        with pytest.raises(ValidationError):
            make_valid_payload(candidates_count=-1)

    def test_candidates_count_zero_allowed(self) -> None:
        """candidates_count of 0 must be valid (edge case: no candidates evaluated)."""
        payload = make_valid_payload(candidates_count=0)
        assert payload.candidates_count == 0

    def test_has_rationale_false(self) -> None:
        """has_rationale=False must be valid (rationale not captured)."""
        payload = make_valid_payload(has_rationale=False)
        assert payload.has_rationale is False


# =============================================================================
# R3: Privacy split — sensitive fields must never be on evt payload
# =============================================================================


class TestDecisionRecordPrivacySplit:
    """R3 — evt payload must not expose sensitive DecisionRecord fields."""

    SENSITIVE_FIELDS = [
        "agent_rationale",
        "reproducibility_snapshot",
        "prompt_text",
        "full_rationale",
        "raw_response",
        "decision_context",
    ]

    def test_evt_payload_has_no_sensitive_fields(self) -> None:
        """ModelHookDecisionRecordedPayload must not declare sensitive field names."""
        declared_fields = set(ModelHookDecisionRecordedPayload.model_fields.keys())
        for sensitive in self.SENSITIVE_FIELDS:
            assert sensitive not in declared_fields, (
                f"Sensitive field '{sensitive}' must not be on the evt payload. "
                f"It belongs exclusively on the cmd topic payload."
            )

    def test_serialized_evt_payload_contains_only_expected_fields(self) -> None:
        """Serialized evt payload must contain only the expected summary fields."""
        payload = make_valid_payload()
        data = payload.model_dump()
        expected_keys = {
            "decision_id",
            "decision_type",
            "selected_candidate",
            "candidates_count",
            "has_rationale",
            "emitted_at",
            "session_id",
        }
        assert set(data.keys()) == expected_keys, (
            f"Unexpected keys in evt payload: {set(data.keys()) - expected_keys}"
        )

    def test_has_rationale_flag_does_not_expose_rationale_text(self) -> None:
        """has_rationale=True must only set a boolean flag, never include the rationale text."""
        payload = make_valid_payload(has_rationale=True)
        data = payload.model_dump()
        # has_rationale should be a bool, not a string/dict containing the rationale
        assert isinstance(data["has_rationale"], bool)
        assert data["has_rationale"] is True

    def test_evt_and_cmd_topic_are_different_access_levels(self) -> None:
        """EVT topic (broad access) and CMD topic (restricted) must be distinct."""
        evt = TopicBase.DECISION_RECORDED_EVT
        cmd = TopicBase.DECISION_RECORDED_CMD
        assert evt.startswith("onex.evt.")
        assert cmd.startswith("onex.cmd.")
        assert evt != cmd

    def test_payload_model_config_is_frozen(self) -> None:
        """model_config frozen=True confirms events are immutable after emission."""
        config = ModelHookDecisionRecordedPayload.model_config
        assert config.get("frozen") is True

    def test_payload_model_config_extra_is_ignore(self) -> None:
        """model_config extra='ignore' confirms sensitive extra fields are silently dropped."""
        config = ModelHookDecisionRecordedPayload.model_config
        assert config.get("extra") == "ignore"
