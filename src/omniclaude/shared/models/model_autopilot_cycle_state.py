# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Autopilot cycle state model for OMN-6491.

Persisted to .onex_state/autopilot-cycle.yaml at each step transition.
Tracks run progress, step outcomes, and circuit-breaker state.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EnumAutopilotStepStatus(StrEnum):
    """Status of an individual autopilot step."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ModelAutopilotStepRecord(BaseModel):
    """Record of a single step execution within an autopilot cycle."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    step_id: str = Field(..., description="Step identifier (e.g. 'A1', 'B5').")
    step_name: str = Field(..., description="Human-readable step name.")
    status: EnumAutopilotStepStatus = Field(
        default=EnumAutopilotStepStatus.PENDING,
        description="Current step status.",
    )
    started_at: datetime | None = Field(
        default=None, description="UTC timestamp when step started."
    )
    completed_at: datetime | None = Field(
        default=None, description="UTC timestamp when step completed."
    )
    error: str | None = Field(
        default=None,
        max_length=2000,
        description="Error message if step failed.",
    )


class ModelAutopilotCycleState(BaseModel):
    """Persistent state for an autopilot cycle.

    Written to .onex_state/autopilot-cycle.yaml at each step transition.
    Enables crash recovery and observability.

    Attributes:
        run_id: Unique identifier for this autopilot run.
        started_at: UTC timestamp when the cycle started.
        current_step: ID of the currently executing step (None if idle).
        steps_completed: Count of successfully completed steps.
        steps_failed: Count of failed steps.
        circuit_breaker_count: Consecutive failure count for circuit breaker.
        last_error: Most recent error message (if any).
        mode: Autopilot mode (build or close-out).
        steps: Ordered list of step execution records.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: UUID = Field(default_factory=uuid.uuid4)
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
    )
    current_step: str | None = Field(
        default=None, description="ID of the currently executing step."
    )
    steps_completed: int = Field(default=0, ge=0)
    steps_failed: int = Field(default=0, ge=0)
    circuit_breaker_count: int = Field(
        default=0,
        ge=0,
        description="Consecutive failure count. Trips at 3.",
    )
    last_error: str | None = Field(
        default=None,
        max_length=2000,
        description="Most recent error message.",
    )
    mode: str = Field(default="close-out", description="build | close-out")
    steps: list[ModelAutopilotStepRecord] = Field(default_factory=list)

    def record_step_start(self, step_id: str, step_name: str) -> None:
        """Record the start of a step. Mutates state in place."""
        self.current_step = step_id
        self.steps.append(
            ModelAutopilotStepRecord(
                step_id=step_id,
                step_name=step_name,
                status=EnumAutopilotStepStatus.RUNNING,
                started_at=datetime.now(UTC),
            )
        )

    def record_step_success(self, step_id: str) -> None:
        """Record successful completion of a step."""
        now = datetime.now(UTC)
        for i, step in enumerate(self.steps):
            if (
                step.step_id == step_id
                and step.status == EnumAutopilotStepStatus.RUNNING
            ):
                self.steps[i] = step.model_copy(
                    update={
                        "status": EnumAutopilotStepStatus.COMPLETED,
                        "completed_at": now,
                    }
                )
                break
        self.steps_completed += 1
        self.circuit_breaker_count = 0
        self.current_step = None
        self.last_error = None

    def record_step_failure(self, step_id: str, error: str) -> bool:
        """Record step failure and increment circuit breaker.

        Returns True if circuit breaker has tripped (>= 3 consecutive failures).
        """
        now = datetime.now(UTC)
        truncated_error = error[:2000] if len(error) > 2000 else error
        for i, step in enumerate(self.steps):
            if (
                step.step_id == step_id
                and step.status == EnumAutopilotStepStatus.RUNNING
            ):
                self.steps[i] = step.model_copy(
                    update={
                        "status": EnumAutopilotStepStatus.FAILED,
                        "completed_at": now,
                        "error": truncated_error,
                    }
                )
                break
        self.steps_failed += 1
        self.circuit_breaker_count += 1
        self.current_step = None
        self.last_error = truncated_error
        return self.circuit_breaker_count >= 3


__all__ = [
    "EnumAutopilotStepStatus",
    "ModelAutopilotCycleState",
    "ModelAutopilotStepRecord",
]
