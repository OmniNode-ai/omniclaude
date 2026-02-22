# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Evidence bundle — immutable artifact linking ticket execution to outcome.

Evidence bundles close the feedback loop: each executed ticket (success or
failure) produces exactly one bundle.  Bundles are never mutated after
capture; they persist for OmniMemory pattern promotion and audit.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from omniclaude.nodes.node_evidence_bundle.enums.enum_execution_outcome import (
    EnumExecutionOutcome,
)
from omniclaude.nodes.node_evidence_bundle.models.model_ac_verification_record import (
    ModelAcVerificationRecord,
)


class ModelEvidenceBundle(BaseModel):
    """Immutable artifact capturing ticket execution outcome.

    Attributes:
        bundle_id: Stable unique ID for this evidence bundle.
        ticket_id: ID of the compiled ticket that was executed.
        work_unit_id: ID of the source Plan DAG work unit.
        dag_id: ID of the Plan DAG containing the work unit.
        intent_id: ID of the originating Intent object.
        nl_input_hash: SHA-256 hash of the original NL input (for traceability).
        outcome: Overall execution outcome.
        ac_records: Per-AC verification records (one per AC in the ticket).
        actual_outputs: Key/value map of actual outputs produced.
        started_at: Explicit start timestamp of ticket execution.
        completed_at: Explicit completion timestamp of ticket execution.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    bundle_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Stable unique ID for this evidence bundle",
    )
    ticket_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="ID of the compiled ticket that was executed",
    )
    work_unit_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="ID of the source Plan DAG work unit",
    )
    dag_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="ID of the Plan DAG containing the work unit",
    )
    intent_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="ID of the originating Intent object",
    )
    nl_input_hash: str = Field(
        ...,
        min_length=64,
        max_length=64,
        description="SHA-256 hex digest of the original NL input",
    )
    outcome: EnumExecutionOutcome = Field(
        ...,
        description="Overall execution outcome",
    )
    ac_records: tuple[ModelAcVerificationRecord, ...] = Field(
        default=(),
        description="Per-AC verification records",
    )
    actual_outputs: tuple[tuple[str, str], ...] = Field(
        default=(),
        description="Actual outputs produced as (key, value) pairs",
    )
    started_at: datetime = Field(
        ...,
        description="Explicit start timestamp of ticket execution",
    )
    completed_at: datetime = Field(
        ...,
        description="Explicit completion timestamp of ticket execution",
    )

    @model_validator(mode="after")
    def _completed_after_started(self) -> ModelEvidenceBundle:
        """Completion timestamp must not precede start timestamp."""
        if self.completed_at < self.started_at:
            raise ValueError(
                f"completed_at ({self.completed_at.isoformat()}) must not be "
                f"before started_at ({self.started_at.isoformat()})"
            )
        return self


__all__ = ["ModelEvidenceBundle"]
