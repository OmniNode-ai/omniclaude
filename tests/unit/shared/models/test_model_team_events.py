# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for unified team event schema (OMN-7026)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from omniclaude.shared.models.model_team_events import (
    ModelEvidenceWrittenEvent,
    ModelTaskAssignedEvent,
    ModelTaskCompletedEvent,
    ModelTaskProgressEvent,
)


@pytest.mark.unit
class TestTeamEventModels:
    """Validate all four team event models."""

    def test_task_assigned_event(self) -> None:
        event = ModelTaskAssignedEvent(
            task_id="task-1",
            session_id="sess-abc",
            correlation_id="corr-123",
            dispatch_surface="team_worker",
            agent_model="claude-opus-4-6",
            agent_name="worker-1",
            team_name="parallel-work",
            contract_path=".onex_state/contracts/task-1.yaml",
            emitted_at=datetime(2026, 3, 30, 12, 0, 0, tzinfo=UTC),
        )
        assert event.dispatch_surface == "team_worker"
        assert event.agent_name == "worker-1"
        assert event.team_name == "parallel-work"
        assert event.contract_path == ".onex_state/contracts/task-1.yaml"
        # Frozen — mutation raises
        with pytest.raises(ValidationError):
            event.task_id = "modified"  # type: ignore[misc]

    def test_task_completed_event(self) -> None:
        event = ModelTaskCompletedEvent(
            task_id="task-1",
            session_id="sess-abc",
            correlation_id="corr-123",
            dispatch_surface="local_llm",
            agent_model="qwen3-14b",
            verification_verdict="PASS",
            evidence_path=".onex_state/evidence/task-1/",
            emitted_at=datetime(2026, 3, 30, 12, 5, 0, tzinfo=UTC),
        )
        assert event.dispatch_surface == "local_llm"
        assert event.verification_verdict == "PASS"
        assert event.token_usage is None
        # Frozen — mutation raises
        with pytest.raises(ValidationError):
            event.verification_verdict = "FAIL"  # type: ignore[misc]

    def test_task_progress_event(self) -> None:
        event = ModelTaskProgressEvent(
            task_id="task-2",
            session_id="sess-def",
            correlation_id="corr-456",
            dispatch_surface="headless_claude",
            agent_model="claude-opus-4-6",
            phase="implementation",
            message="Tests passing",
            emitted_at=datetime(2026, 3, 30, 12, 3, 0, tzinfo=UTC),
        )
        assert event.phase == "implementation"
        assert event.message == "Tests passing"
        assert event.checkpoint_path is None

    def test_evidence_written_event(self) -> None:
        event = ModelEvidenceWrittenEvent(
            task_id="task-3",
            session_id="sess-ghi",
            correlation_id="corr-789",
            dispatch_surface="team_worker",
            agent_model="deepseek-r1",
            evidence_type="self_check",
            evidence_path=".onex_state/evidence/task-3/self-check.yaml",
            passed=True,
            emitted_at=datetime(2026, 3, 30, 12, 4, 0, tzinfo=UTC),
        )
        assert event.evidence_type == "self_check"
        assert event.passed is True

    def test_emitted_at_required(self) -> None:
        """emitted_at must be explicitly provided — no default."""
        with pytest.raises(ValidationError):
            ModelTaskAssignedEvent(
                task_id="task-1",
                session_id="sess-abc",
                correlation_id="corr-123",
                dispatch_surface="team_worker",
                agent_model="claude-opus-4-6",
                agent_name="worker-1",
                # emitted_at intentionally omitted
            )

    def test_extra_fields_ignored(self) -> None:
        """Extra fields should be silently ignored (extra='ignore')."""
        event = ModelTaskAssignedEvent(
            task_id="task-1",
            session_id="sess-abc",
            correlation_id="corr-123",
            dispatch_surface="team_worker",
            agent_model="claude-opus-4-6",
            agent_name="worker-1",
            emitted_at=datetime(2026, 3, 30, 12, 0, 0, tzinfo=UTC),
            unknown_field="should be ignored",  # type: ignore[call-arg]
        )
        assert not hasattr(event, "unknown_field")
