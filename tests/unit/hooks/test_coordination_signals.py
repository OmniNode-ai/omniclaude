# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for coordination signal models and event registry wiring (OMN-6857)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from omniclaude.hooks.coordination import (
    EnumCoordinationSignalType,
    ModelCoordinationSignal,
    ModelCoordinationSignalPayload,
)
from omniclaude.hooks.event_registry import EVENT_REGISTRY, validate_payload
from omniclaude.hooks.topics import TopicBase

pytestmark = pytest.mark.unit


# =============================================================================
# EnumCoordinationSignalType tests
# =============================================================================


class TestEnumCoordinationSignalType:
    """Test signal type enum."""

    def test_all_expected_values_exist(self) -> None:
        expected = {
            "pr_merged",
            "rebase_needed",
            "conflict_detected",
            "ticket_claimed",
            "ticket_completed",
            "files_changed",
        }
        actual = {member.value for member in EnumCoordinationSignalType}
        assert actual == expected

    def test_is_str_enum(self) -> None:
        assert isinstance(EnumCoordinationSignalType.PR_MERGED, str)
        assert EnumCoordinationSignalType.PR_MERGED == "pr_merged"


# =============================================================================
# ModelCoordinationSignalPayload tests
# =============================================================================


class TestModelCoordinationSignalPayload:
    """Test coordination signal payload model."""

    def _make_payload(self, **overrides: object) -> ModelCoordinationSignalPayload:
        defaults: dict[str, object] = {
            "repo": "OmniNode-ai/omniclaude",
        }
        defaults.update(overrides)
        return ModelCoordinationSignalPayload(**defaults)  # type: ignore[arg-type]

    def test_minimal_payload(self) -> None:
        payload = self._make_payload()
        assert payload.repo == "OmniNode-ai/omniclaude"
        assert payload.file_paths == []
        assert payload.pr_number is None
        assert payload.related_task_id is None
        assert payload.reason == ""
        assert payload.extra == {}

    def test_full_payload(self) -> None:
        payload = self._make_payload(
            file_paths=["src/foo.py", "src/bar.py"],
            pr_number=42,
            related_task_id="OMN-1234",
            reason="PR merged to main",
            extra={"merge_sha": "abc123"},
        )
        assert payload.file_paths == ["src/foo.py", "src/bar.py"]
        assert payload.pr_number == 42
        assert payload.related_task_id == "OMN-1234"
        assert payload.reason == "PR merged to main"
        assert payload.extra == {"merge_sha": "abc123"}

    def test_frozen(self) -> None:
        payload = self._make_payload()
        with pytest.raises(ValidationError):
            payload.repo = "other"  # type: ignore[misc]

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            self._make_payload(unknown_field="nope")

    def test_repo_required(self) -> None:
        with pytest.raises(ValidationError):
            ModelCoordinationSignalPayload()  # type: ignore[call-arg]

    def test_serializes_correctly(self) -> None:
        payload = self._make_payload(
            pr_number=99,
            reason="test",
        )
        data = payload.model_dump(mode="json")
        assert data["repo"] == "OmniNode-ai/omniclaude"
        assert data["pr_number"] == 99
        assert data["reason"] == "test"


# =============================================================================
# ModelCoordinationSignal tests
# =============================================================================


class TestModelCoordinationSignal:
    """Test full coordination signal envelope."""

    def _make_signal(self, **overrides: object) -> ModelCoordinationSignal:
        defaults: dict[str, object] = {
            "signal_id": uuid4(),
            "signal_type": EnumCoordinationSignalType.PR_MERGED,
            "task_id": "OMN-1234",
            "session_id": "sess-001",
            "payload": ModelCoordinationSignalPayload(
                repo="OmniNode-ai/omniclaude",
                pr_number=42,
                reason="PR merged",
            ),
            "emitted_at": datetime(2026, 3, 27, 12, 0, 0, tzinfo=UTC),
        }
        defaults.update(overrides)
        return ModelCoordinationSignal(**defaults)  # type: ignore[arg-type]

    def test_pr_merged_signal(self) -> None:
        signal = self._make_signal()
        assert signal.signal_type == EnumCoordinationSignalType.PR_MERGED
        assert signal.task_id == "OMN-1234"
        assert signal.session_id == "sess-001"
        assert signal.payload.repo == "OmniNode-ai/omniclaude"
        assert signal.payload.pr_number == 42

    def test_rebase_needed_signal(self) -> None:
        signal = self._make_signal(
            signal_type=EnumCoordinationSignalType.REBASE_NEEDED,
            payload=ModelCoordinationSignalPayload(
                repo="OmniNode-ai/omniclaude",
                file_paths=["src/hooks/schemas.py"],
                reason="Upstream changes on main",
            ),
        )
        assert signal.signal_type == EnumCoordinationSignalType.REBASE_NEEDED
        assert signal.payload.file_paths == ["src/hooks/schemas.py"]

    def test_conflict_detected_signal(self) -> None:
        signal = self._make_signal(
            signal_type=EnumCoordinationSignalType.CONFLICT_DETECTED,
            payload=ModelCoordinationSignalPayload(
                repo="OmniNode-ai/omniclaude",
                file_paths=["src/hooks/topics.py"],
                related_task_id="OMN-5678",
                reason="Both sessions modifying topics.py",
            ),
        )
        assert signal.signal_type == EnumCoordinationSignalType.CONFLICT_DETECTED
        assert signal.payload.related_task_id == "OMN-5678"

    def test_ticket_claimed_signal(self) -> None:
        signal = self._make_signal(
            signal_type=EnumCoordinationSignalType.TICKET_CLAIMED,
        )
        assert signal.signal_type == EnumCoordinationSignalType.TICKET_CLAIMED

    def test_ticket_completed_signal(self) -> None:
        signal = self._make_signal(
            signal_type=EnumCoordinationSignalType.TICKET_COMPLETED,
        )
        assert signal.signal_type == EnumCoordinationSignalType.TICKET_COMPLETED

    def test_files_changed_signal(self) -> None:
        signal = self._make_signal(
            signal_type=EnumCoordinationSignalType.FILES_CHANGED,
            payload=ModelCoordinationSignalPayload(
                repo="OmniNode-ai/omniclaude",
                file_paths=["src/hooks/event_registry.py"],
                reason="Event registry updated",
            ),
        )
        assert signal.signal_type == EnumCoordinationSignalType.FILES_CHANGED

    def test_frozen(self) -> None:
        signal = self._make_signal()
        with pytest.raises(ValidationError):
            signal.task_id = "other"  # type: ignore[misc]

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            self._make_signal(unknown_field="nope")

    def test_emitted_at_required(self) -> None:
        """emitted_at has no default — must be explicitly injected."""
        with pytest.raises(ValidationError):
            ModelCoordinationSignal(
                signal_id=uuid4(),
                signal_type=EnumCoordinationSignalType.PR_MERGED,
                task_id="OMN-1234",
                session_id="sess-001",
                payload=ModelCoordinationSignalPayload(
                    repo="OmniNode-ai/omniclaude",
                ),
            )  # type: ignore[call-arg]

    def test_serializes_round_trip(self) -> None:
        signal = self._make_signal()
        data = signal.model_dump(mode="json")
        restored = ModelCoordinationSignal(**data)
        assert restored.signal_type == signal.signal_type
        assert restored.task_id == signal.task_id
        assert restored.payload.repo == signal.payload.repo


# =============================================================================
# Event Registry Wiring tests
# =============================================================================


class TestCoordinationEventRegistryWiring:
    """Test that coordination.signal is properly wired in EVENT_REGISTRY."""

    def test_event_type_registered(self) -> None:
        assert "coordination.signal" in EVENT_REGISTRY

    def test_fan_out_targets_correct_topic(self) -> None:
        reg = EVENT_REGISTRY["coordination.signal"]
        assert len(reg.fan_out) == 1
        assert reg.fan_out[0].topic_base == TopicBase.SESSION_COORDINATION_SIGNAL

    def test_partition_key_is_session_id(self) -> None:
        reg = EVENT_REGISTRY["coordination.signal"]
        assert reg.partition_key_field == "session_id"

    def test_required_fields(self) -> None:
        reg = EVENT_REGISTRY["coordination.signal"]
        assert "session_id" in reg.required_fields
        assert "signal_type" in reg.required_fields
        assert "task_id" in reg.required_fields

    def test_validate_payload_passes_with_valid_data(self) -> None:
        missing = validate_payload(
            "coordination.signal",
            {
                "session_id": "sess-001",
                "signal_type": "pr_merged",
                "task_id": "OMN-1234",
            },
        )
        assert missing == []

    def test_validate_payload_fails_missing_fields(self) -> None:
        missing = validate_payload(
            "coordination.signal",
            {"session_id": "sess-001"},
        )
        assert "signal_type" in missing
        assert "task_id" in missing


# =============================================================================
# Topic tests
# =============================================================================


class TestCoordinationTopics:
    """Test that coordination topics are properly defined."""

    def test_session_coordination_signal_topic_exists(self) -> None:
        assert hasattr(TopicBase, "SESSION_COORDINATION_SIGNAL")
        assert (
            TopicBase.SESSION_COORDINATION_SIGNAL
            == "onex.evt.omniclaude.session-coordination-signal.v1"
        )

    def test_session_status_changed_topic_exists(self) -> None:
        assert hasattr(TopicBase, "SESSION_STATUS_CHANGED")
        assert (
            TopicBase.SESSION_STATUS_CHANGED
            == "onex.evt.omniclaude.session-status-changed.v1"
        )

    def test_topics_follow_onex_naming(self) -> None:
        """Topics must follow onex.{kind}.{producer}.{event-name}.v{n} format."""
        for topic in [
            TopicBase.SESSION_COORDINATION_SIGNAL,
            TopicBase.SESSION_STATUS_CHANGED,
        ]:
            parts = topic.split(".")
            assert parts[0] == "onex"
            assert parts[1] in ("evt", "cmd")
            assert parts[2] == "omniclaude"
            assert parts[-1].startswith("v")
