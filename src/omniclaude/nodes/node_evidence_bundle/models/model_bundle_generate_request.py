# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Input model for the evidence bundle generator."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.nodes.node_evidence_bundle.enums.enum_execution_outcome import (
    EnumExecutionOutcome,
)
from omniclaude.nodes.node_evidence_bundle.models.model_ac_verification_record import (
    ModelAcVerificationRecord,
)


class ModelBundleGenerateRequest(BaseModel):
    """Request to generate an evidence bundle from a ticket execution.

    Attributes:
        ticket_id: ID of the compiled ticket that was executed.
        work_unit_id: ID of the source Plan DAG work unit.
        dag_id: ID of the Plan DAG containing the work unit.
        intent_id: ID of the originating Intent object.
        nl_input_hash: SHA-256 hash of the original NL input.
        outcome: Overall execution outcome.
        ac_records: Per-AC verification records collected during execution.
        actual_outputs: Actual outputs produced as (key, value) pairs.
        started_at: Explicit start timestamp (injected by caller).
        completed_at: Explicit completion timestamp (injected by caller).
        correlation_id: Correlation UUID for distributed tracing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

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
        description="Per-AC verification records from execution",
    )
    actual_outputs: tuple[tuple[str, str], ...] = Field(
        default=(),
        description="Actual outputs produced as (key, value) pairs",
    )
    started_at: datetime = Field(
        ...,
        description="Explicit start timestamp (injected by caller, not defaulted)",
    )
    completed_at: datetime = Field(
        ...,
        description="Explicit completion timestamp (injected by caller, not defaulted)",
    )
    correlation_id: UUID = Field(
        ...,
        description="Correlation UUID for distributed tracing",
    )


__all__ = ["ModelBundleGenerateRequest"]
