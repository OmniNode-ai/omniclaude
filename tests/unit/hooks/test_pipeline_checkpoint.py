# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for pipeline checkpointing (OMN-6818)."""

from __future__ import annotations

from pathlib import Path

import pytest

from omniclaude.hooks.pipeline_checkpoint import (
    EnumCheckpointPhaseStatus,
    ModelPhaseState,
    ModelPipelineCheckpoint,
    PipelineCheckpointManager,
)


@pytest.mark.unit
class TestModelPhaseState:
    """Tests for ModelPhaseState model."""

    def test_defaults(self) -> None:
        phase = ModelPhaseState(name="implement")
        assert phase.name == "implement"
        assert phase.status == EnumCheckpointPhaseStatus.PENDING
        assert phase.started_at is None
        assert phase.completed_at is None
        assert phase.artifacts == {}
        assert phase.error is None

    def test_with_status(self) -> None:
        phase = ModelPhaseState(
            name="review",
            status=EnumCheckpointPhaseStatus.COMPLETED,
        )
        assert phase.status == EnumCheckpointPhaseStatus.COMPLETED


@pytest.mark.unit
class TestModelPipelineCheckpoint:
    """Tests for ModelPipelineCheckpoint model."""

    def test_create_minimal(self) -> None:
        cp = ModelPipelineCheckpoint(
            run_id="test-run-123",
            ticket_id="OMN-1234",
            skill_name="ticket-pipeline",
            created_at="2026-03-28T00:00:00+00:00",
            updated_at="2026-03-28T00:00:00+00:00",
        )
        assert cp.run_id == "test-run-123"
        assert cp.ticket_id == "OMN-1234"
        assert cp.phases == []
        assert cp.current_phase is None

    def test_with_phases(self) -> None:
        phases = [
            ModelPhaseState(name="pre_flight"),
            ModelPhaseState(name="implement"),
            ModelPhaseState(name="review"),
        ]
        cp = ModelPipelineCheckpoint(
            run_id="test-run",
            ticket_id="OMN-1234",
            skill_name="ticket-pipeline",
            phases=phases,
            created_at="2026-03-28T00:00:00+00:00",
            updated_at="2026-03-28T00:00:00+00:00",
        )
        assert len(cp.phases) == 3
        assert cp.phases[0].name == "pre_flight"

    def test_metadata(self) -> None:
        cp = ModelPipelineCheckpoint(
            run_id="test-run",
            ticket_id="OMN-1234",
            skill_name="ticket-pipeline",
            metadata={"branch": "feature/test"},
            created_at="2026-03-28T00:00:00+00:00",
            updated_at="2026-03-28T00:00:00+00:00",
        )
        assert cp.metadata["branch"] == "feature/test"


@pytest.mark.unit
class TestPipelineCheckpointManager:
    """Tests for PipelineCheckpointManager."""

    def test_create_checkpoint(self, tmp_path: Path) -> None:
        mgr = PipelineCheckpointManager(state_dir=tmp_path)
        cp = mgr.create(
            run_id="run-001",
            ticket_id="OMN-5555",
            skill_name="ticket-pipeline",
            phase_names=["pre_flight", "implement", "review"],
        )
        assert cp.run_id == "run-001"
        assert len(cp.phases) == 3
        assert all(p.status == EnumCheckpointPhaseStatus.PENDING for p in cp.phases)

    def test_save_and_load(self, tmp_path: Path) -> None:
        mgr = PipelineCheckpointManager(state_dir=tmp_path)
        cp = mgr.create(
            run_id="run-002",
            ticket_id="OMN-6666",
            skill_name="epic-team",
            phase_names=["phase1", "phase2"],
        )

        loaded = mgr.load("run-002")
        assert loaded is not None
        assert loaded.run_id == "run-002"
        assert loaded.ticket_id == "OMN-6666"
        assert len(loaded.phases) == 2

    def test_load_nonexistent_returns_none(self, tmp_path: Path) -> None:
        mgr = PipelineCheckpointManager(state_dir=tmp_path)
        result = mgr.load("nonexistent-run")
        assert result is None

    def test_start_phase(self, tmp_path: Path) -> None:
        mgr = PipelineCheckpointManager(state_dir=tmp_path)
        cp = mgr.create(
            run_id="run-003",
            ticket_id="OMN-7777",
            skill_name="test",
            phase_names=["a", "b", "c"],
        )

        cp = mgr.start_phase(cp, "a")
        assert cp.current_phase == "a"
        assert cp.phases[0].status == EnumCheckpointPhaseStatus.IN_PROGRESS
        assert cp.phases[0].started_at is not None

    def test_complete_phase(self, tmp_path: Path) -> None:
        mgr = PipelineCheckpointManager(state_dir=tmp_path)
        cp = mgr.create(
            run_id="run-004",
            ticket_id="OMN-8888",
            skill_name="test",
            phase_names=["a", "b", "c"],
        )

        cp = mgr.start_phase(cp, "a")
        cp = mgr.complete_phase(cp, "a", artifacts={"key": "value"})

        assert cp.phases[0].status == EnumCheckpointPhaseStatus.COMPLETED
        assert cp.phases[0].completed_at is not None
        assert cp.phases[0].artifacts == {"key": "value"}
        # current_phase should advance to next pending
        assert cp.current_phase == "b"

    def test_fail_phase(self, tmp_path: Path) -> None:
        mgr = PipelineCheckpointManager(state_dir=tmp_path)
        cp = mgr.create(
            run_id="run-005",
            ticket_id="OMN-9999",
            skill_name="test",
            phase_names=["a", "b"],
        )

        cp = mgr.start_phase(cp, "a")
        cp = mgr.fail_phase(cp, "a", error="Something went wrong")

        assert cp.phases[0].status == EnumCheckpointPhaseStatus.FAILED
        assert cp.phases[0].error == "Something went wrong"

    def test_get_completed_phases(self, tmp_path: Path) -> None:
        mgr = PipelineCheckpointManager(state_dir=tmp_path)
        cp = mgr.create(
            run_id="run-006",
            ticket_id="OMN-1111",
            skill_name="test",
            phase_names=["a", "b", "c"],
        )

        cp = mgr.start_phase(cp, "a")
        cp = mgr.complete_phase(cp, "a")
        cp = mgr.start_phase(cp, "b")
        cp = mgr.complete_phase(cp, "b")

        completed = mgr.get_completed_phases(cp)
        assert completed == ["a", "b"]

    def test_should_skip_phase(self, tmp_path: Path) -> None:
        mgr = PipelineCheckpointManager(state_dir=tmp_path)
        cp = mgr.create(
            run_id="run-007",
            ticket_id="OMN-2222",
            skill_name="test",
            phase_names=["a", "b", "c"],
        )

        cp = mgr.start_phase(cp, "a")
        cp = mgr.complete_phase(cp, "a")

        assert mgr.should_skip_phase(cp, "a") is True
        assert mgr.should_skip_phase(cp, "b") is False
        assert mgr.should_skip_phase(cp, "nonexistent") is False

    def test_persistence_roundtrip(self, tmp_path: Path) -> None:
        """Verify checkpoint survives a save/load/modify/save/load cycle."""
        mgr = PipelineCheckpointManager(state_dir=tmp_path)
        cp = mgr.create(
            run_id="run-008",
            ticket_id="OMN-3333",
            skill_name="test",
            phase_names=["x", "y"],
            metadata={"mode": "autonomous"},
        )

        # Modify and reload
        cp = mgr.start_phase(cp, "x")
        cp = mgr.complete_phase(cp, "x", artifacts={"branch": "feat/test"})

        loaded = mgr.load("run-008")
        assert loaded is not None
        assert loaded.phases[0].status == EnumCheckpointPhaseStatus.COMPLETED
        assert loaded.phases[0].artifacts == {"branch": "feat/test"}
        assert loaded.metadata == {"mode": "autonomous"}
        assert loaded.current_phase == "y"

    def test_env_state_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Manager uses ONEX_STATE_DIR env var when no explicit dir given."""
        monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))
        mgr = PipelineCheckpointManager()
        cp = mgr.create(
            run_id="run-env",
            ticket_id="OMN-4444",
            skill_name="test",
            phase_names=["a"],
        )
        assert (tmp_path / "checkpoint-run-env.yaml").exists()
