# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Pipeline checkpointing for long-running skills (OMN-6818).

Provides a Pydantic model and manager for saving/loading pipeline state at
phase boundaries. This prevents context overflow in long-running pipeline
skills (ticket-pipeline, epic-team) by enabling resume from the last
completed phase.

State is persisted to `.onex_state/checkpoint-{run_id}.yaml`.

Key differences from the infrastructure-level checkpoint system (OMN-2143):
- This is skill-level checkpointing: tracks which *skill phases* completed.
- The infra checkpoint system tracks *pipeline phases* with rich payloads.
- This system is lightweight (single YAML file per run) and self-contained.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

# Default state directory
_DEFAULT_STATE_DIR = ".onex_state"


class EnumCheckpointPhaseStatus(StrEnum):
    """Status of a checkpoint phase."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ModelPhaseState(BaseModel):
    """State of a single pipeline phase.

    Attributes:
        name: Phase name (e.g., 'pre_flight', 'implement').
        status: Current status of this phase.
        started_at: When this phase started.
        completed_at: When this phase completed.
        artifacts: Key-value pairs of phase outputs (e.g., branch_name, pr_url).
        error: Error message if phase failed.
    """

    model_config = ConfigDict(frozen=False, extra="forbid")

    name: str = Field(description="Phase name")
    status: EnumCheckpointPhaseStatus = Field(
        default=EnumCheckpointPhaseStatus.PENDING,
        description="Current phase status",
    )
    started_at: str | None = Field(default=None, description="ISO-8601 start time")
    completed_at: str | None = Field(
        default=None, description="ISO-8601 completion time"
    )
    artifacts: dict[str, str] = Field(
        default_factory=dict,
        description="Phase output artifacts",
    )
    error: str | None = Field(default=None, description="Error message if failed")


class ModelPipelineCheckpoint(BaseModel):
    """Checkpoint state for a long-running pipeline skill.

    Persisted to `.onex_state/checkpoint-{run_id}.yaml` at each phase boundary.
    On resume, the manager loads this checkpoint and skips completed phases.

    Attributes:
        schema_version: Forward-compatibility version string.
        run_id: Unique identifier for this pipeline run.
        ticket_id: Linear ticket being processed.
        skill_name: Name of the pipeline skill (e.g., 'ticket-pipeline').
        current_phase: Name of the phase currently in progress.
        phases: Ordered list of phase states.
        created_at: When this checkpoint was first created.
        updated_at: When this checkpoint was last updated.
        metadata: Arbitrary metadata for the pipeline run.
    """

    model_config = ConfigDict(frozen=False, extra="forbid")

    schema_version: str = Field(
        default="1.0.0", description="Checkpoint schema version"
    )
    run_id: str = Field(description="Pipeline run ID")
    ticket_id: str = Field(description="Linear ticket ID")
    skill_name: str = Field(description="Pipeline skill name")
    current_phase: str | None = Field(
        default=None, description="Currently active phase"
    )
    phases: list[ModelPhaseState] = Field(
        default_factory=list, description="Ordered phase states"
    )
    created_at: str = Field(description="ISO-8601 creation timestamp")
    updated_at: str = Field(description="ISO-8601 last update timestamp")
    metadata: dict[str, str] = Field(
        default_factory=dict, description="Arbitrary metadata"
    )


class PipelineCheckpointManager:
    """Manages checkpoint persistence for pipeline skills.

    Provides save, load, and phase transition operations. Checkpoints are
    stored as YAML files in the `.onex_state` directory.

    Args:
        state_dir: Directory for checkpoint files. Defaults to `.onex_state`
            relative to the project root, or $ONEX_STATE_DIR if set.
    """

    def __init__(self, state_dir: Path | None = None) -> None:
        if state_dir is not None:
            self._state_dir = state_dir
        else:
            env_dir = os.getenv("ONEX_STATE_DIR")
            if env_dir:
                self._state_dir = Path(env_dir)
            else:
                self._state_dir = Path(_DEFAULT_STATE_DIR)

    def _checkpoint_path(self, run_id: str) -> Path:
        """Return the file path for a checkpoint."""
        return self._state_dir / f"checkpoint-{run_id}.yaml"

    def save(self, checkpoint: ModelPipelineCheckpoint) -> Path:
        """Save a checkpoint to disk.

        Args:
            checkpoint: The checkpoint to save.

        Returns:
            Path to the saved checkpoint file.
        """
        path = self._checkpoint_path(checkpoint.run_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Update timestamp
        checkpoint.updated_at = datetime.now(UTC).isoformat()

        # Atomic write via tmp file
        tmp_path = path.with_suffix(".yaml.tmp")
        data = checkpoint.model_dump(mode="json")
        tmp_path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
        tmp_path.rename(path)

        logger.debug("Checkpoint saved: %s", path)
        return path

    def load(self, run_id: str) -> ModelPipelineCheckpoint | None:
        """Load a checkpoint from disk.

        Args:
            run_id: The pipeline run ID.

        Returns:
            The loaded checkpoint, or None if not found or corrupt.
        """
        path = self._checkpoint_path(run_id)
        if not path.exists():
            return None

        try:
            data = yaml.safe_load(path.read_text())
            return ModelPipelineCheckpoint.model_validate(data)
        except (yaml.YAMLError, ValueError, TypeError, OSError):
            logger.warning("Failed to load checkpoint %s", path, exc_info=True)
            return None

    def create(
        self,
        run_id: str,
        ticket_id: str,
        skill_name: str,
        phase_names: list[str],
        metadata: dict[str, str] | None = None,
    ) -> ModelPipelineCheckpoint:
        """Create a new checkpoint with pending phases.

        Args:
            run_id: Pipeline run ID.
            ticket_id: Linear ticket ID.
            skill_name: Name of the pipeline skill.
            phase_names: Ordered list of phase names.
            metadata: Optional metadata dict.

        Returns:
            New checkpoint with all phases in PENDING status.
        """
        now = datetime.now(UTC).isoformat()
        phases = [ModelPhaseState(name=name) for name in phase_names]
        checkpoint = ModelPipelineCheckpoint(
            run_id=run_id,
            ticket_id=ticket_id,
            skill_name=skill_name,
            phases=phases,
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )
        self.save(checkpoint)
        return checkpoint

    def start_phase(
        self, checkpoint: ModelPipelineCheckpoint, phase_name: str
    ) -> ModelPipelineCheckpoint:
        """Mark a phase as in-progress.

        Args:
            checkpoint: Current checkpoint state.
            phase_name: Name of the phase to start.

        Returns:
            Updated checkpoint.
        """
        for phase in checkpoint.phases:
            if phase.name == phase_name:
                phase.status = EnumCheckpointPhaseStatus.IN_PROGRESS
                phase.started_at = datetime.now(UTC).isoformat()
                break

        checkpoint.current_phase = phase_name
        self.save(checkpoint)
        return checkpoint

    def complete_phase(
        self,
        checkpoint: ModelPipelineCheckpoint,
        phase_name: str,
        artifacts: dict[str, str] | None = None,
    ) -> ModelPipelineCheckpoint:
        """Mark a phase as completed.

        Args:
            checkpoint: Current checkpoint state.
            phase_name: Name of the phase to complete.
            artifacts: Optional artifacts produced by this phase.

        Returns:
            Updated checkpoint.
        """
        for phase in checkpoint.phases:
            if phase.name == phase_name:
                phase.status = EnumCheckpointPhaseStatus.COMPLETED
                phase.completed_at = datetime.now(UTC).isoformat()
                if artifacts:
                    phase.artifacts.update(artifacts)
                break

        # Advance current_phase to next pending phase
        checkpoint.current_phase = None
        for phase in checkpoint.phases:
            if phase.status == EnumCheckpointPhaseStatus.PENDING:
                checkpoint.current_phase = phase.name
                break

        self.save(checkpoint)
        return checkpoint

    def fail_phase(
        self,
        checkpoint: ModelPipelineCheckpoint,
        phase_name: str,
        error: str,
    ) -> ModelPipelineCheckpoint:
        """Mark a phase as failed.

        Args:
            checkpoint: Current checkpoint state.
            phase_name: Name of the phase that failed.
            error: Error description.

        Returns:
            Updated checkpoint.
        """
        for phase in checkpoint.phases:
            if phase.name == phase_name:
                phase.status = EnumCheckpointPhaseStatus.FAILED
                phase.completed_at = datetime.now(UTC).isoformat()
                phase.error = error
                break

        self.save(checkpoint)
        return checkpoint

    def get_completed_phases(self, checkpoint: ModelPipelineCheckpoint) -> list[str]:
        """Return names of all completed phases.

        Args:
            checkpoint: Current checkpoint state.

        Returns:
            List of completed phase names.
        """
        return [
            p.name
            for p in checkpoint.phases
            if p.status == EnumCheckpointPhaseStatus.COMPLETED
        ]

    def should_skip_phase(
        self, checkpoint: ModelPipelineCheckpoint, phase_name: str
    ) -> bool:
        """Check if a phase should be skipped (already completed).

        Args:
            checkpoint: Current checkpoint state.
            phase_name: Phase to check.

        Returns:
            True if the phase is already completed and should be skipped.
        """
        for phase in checkpoint.phases:
            if phase.name == phase_name:
                return phase.status == EnumCheckpointPhaseStatus.COMPLETED
        return False


__all__ = [
    "EnumCheckpointPhaseStatus",
    "ModelPhaseState",
    "ModelPipelineCheckpoint",
    "PipelineCheckpointManager",
]
