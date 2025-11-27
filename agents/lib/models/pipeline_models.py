#!/usr/bin/env python3
"""
Pipeline models for autonomous node generation POC.

Defines data structures for tracking pipeline execution, validation gates,
and stage progress across the 6-stage generation pipeline.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StageStatus(str, Enum):
    """Pipeline stage execution status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class GateType(str, Enum):
    """Validation gate types."""

    BLOCKING = "blocking"  # Must pass for pipeline to continue
    WARNING = "warning"  # Log warning but continue


class ValidationGate(BaseModel):
    """
    Validation gate result.

    Tracks individual validation gate execution with timing and status.
    Target: <200ms execution per gate.
    """

    gate_id: str = Field(..., description="Gate identifier (G1, G2, etc.)")
    name: str = Field(..., description="Human-readable gate name")
    status: str = Field(..., description="Gate status: pass/fail/warning/skipped")
    gate_type: GateType = Field(
        default=GateType.BLOCKING, description="Gate type (blocking/warning)"
    )
    message: str | None = Field(
        default=None, description="Status message or error details"
    )
    duration_ms: int = Field(..., description="Gate execution time in milliseconds")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Gate execution timestamp",
    )

    model_config = ConfigDict(json_encoders={datetime: lambda v: v.isoformat()})


class PipelineStage(BaseModel):
    """
    Pipeline stage tracking.

    Tracks individual stage execution with validation gates, timing, and errors.
    Includes performance tracking against target thresholds.
    """

    stage_name: str = Field(..., description="Stage identifier")
    status: StageStatus = Field(
        default=StageStatus.PENDING, description="Stage execution status"
    )
    start_time: datetime | None = Field(
        default=None, description="Stage start timestamp"
    )
    end_time: datetime | None = Field(default=None, description="Stage end timestamp")
    duration_ms: int | None = Field(
        default=None, description="Stage execution time in milliseconds"
    )
    validation_gates: list[ValidationGate] = Field(
        default_factory=list, description="Validation gates executed in this stage"
    )
    error: str | None = Field(default=None, description="Error message if stage failed")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Stage-specific metadata"
    )

    # Performance tracking fields (NEW)
    performance_target_ms: int = Field(
        default=0, description="Target performance threshold in milliseconds"
    )
    actual_duration_ms: int = Field(
        default=0, description="Actual execution duration in milliseconds"
    )
    performance_ratio: float = Field(
        default=0.0,
        description="Performance ratio (actual/target) - <1.0 is good, >1.0 is slow",
    )

    model_config = ConfigDict(json_encoders={datetime: lambda v: v.isoformat()})

    def calculate_performance_ratio(self) -> float:
        """
        Calculate performance ratio (actual vs target).

        Returns:
            Performance ratio where:
            - <1.0 = Better than target (good)
            - 1.0 = Exactly on target
            - >1.0 = Slower than target (needs attention)
            - 0.0 = No target set or no actual duration
        """
        if self.performance_target_ms > 0 and self.actual_duration_ms > 0:
            return self.actual_duration_ms / self.performance_target_ms
        return 0.0

    def update_performance_metrics(self, target_ms: int) -> None:
        """
        Update performance metrics based on stage duration.

        Args:
            target_ms: Target performance threshold in milliseconds
        """
        self.performance_target_ms = target_ms
        if self.duration_ms is not None:
            self.actual_duration_ms = self.duration_ms
            self.performance_ratio = self.calculate_performance_ratio()


class PipelineResult(BaseModel):
    """
    Complete pipeline execution result.

    Comprehensive result object tracking all stages, validation gates,
    generated files, and execution metadata.
    """

    correlation_id: UUID = Field(..., description="Pipeline execution correlation ID")
    status: str = Field(
        ..., description="Overall pipeline status: success/failed/partial"
    )
    total_duration_ms: int = Field(
        ..., description="Total pipeline execution time in milliseconds"
    )
    stages: list[PipelineStage] = Field(
        default_factory=list, description="All pipeline stages"
    )
    output_path: str | None = Field(
        default=None, description="Output directory path (if successful)"
    )
    generated_files: list[str] = Field(
        default_factory=list, description="List of generated file paths"
    )
    node_type: str | None = Field(
        default=None, description="Generated node type (EFFECT, COMPUTE, etc.)"
    )
    service_name: str | None = Field(default=None, description="Generated service name")
    domain: str | None = Field(default=None, description="Generated node domain")
    validation_passed: bool = Field(
        default=False, description="Whether all validation gates passed"
    )
    compilation_passed: bool = Field(
        default=False, description="Whether compilation testing passed"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Pipeline execution metadata"
    )
    error_summary: str | None = Field(
        default=None, description="High-level error summary if pipeline failed"
    )

    model_config = ConfigDict(
        json_encoders={datetime: lambda v: v.isoformat(), UUID: str}
    )

    @property
    def success(self) -> bool:
        """Check if pipeline completed successfully."""
        return self.status == "success"

    @property
    def duration_seconds(self) -> float:
        """Get total duration in seconds."""
        return self.total_duration_ms / 1000.0

    def get_stage(self, stage_name: str) -> PipelineStage | None:
        """Get stage by name."""
        for stage in self.stages:
            if stage.stage_name == stage_name:
                return stage
        return None

    def get_failed_gates(self) -> list[ValidationGate]:
        """Get all failed validation gates."""
        failed = []
        for stage in self.stages:
            for gate in stage.validation_gates:
                if gate.status == "fail":
                    failed.append(gate)
        return failed

    def get_warning_gates(self) -> list[ValidationGate]:
        """Get all warning validation gates."""
        warnings = []
        for stage in self.stages:
            for gate in stage.validation_gates:
                if gate.status == "warning":
                    warnings.append(gate)
        return warnings

    def to_summary(self) -> str:
        """Generate human-readable summary."""
        lines = [
            f"Pipeline Result: {self.status.upper()}",
            f"Duration: {self.duration_seconds:.2f}s",
            f"Stages: {len(self.stages)}",
        ]

        if self.node_type:
            lines.append(f"Node Type: {self.node_type}")
        if self.service_name:
            lines.append(f"Service: {self.service_name}")
        if self.generated_files:
            lines.append(f"Files Generated: {len(self.generated_files)}")

        # Failed gates
        failed_gates = self.get_failed_gates()
        if failed_gates:
            lines.append(f"\nFailed Gates ({len(failed_gates)}):")
            for gate in failed_gates:
                lines.append(f"  - {gate.gate_id}: {gate.message}")

        # Warning gates
        warning_gates = self.get_warning_gates()
        if warning_gates:
            lines.append(f"\nWarning Gates ({len(warning_gates)}):")
            for gate in warning_gates:
                lines.append(f"  - {gate.gate_id}: {gate.message}")

        if self.error_summary:
            lines.append(f"\nError: {self.error_summary}")

        return "\n".join(lines)
