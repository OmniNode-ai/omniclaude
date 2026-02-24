# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Compiled ticket model — the output of Stage 4.

Each compiled ticket corresponds to exactly one work unit from the Plan DAG
and is ready for submission to Linear.  Tickets without at least one
verifiable acceptance criterion are rejected at construction time.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from omniclaude.nodes.node_ticket_compiler.enums.enum_assertion_type import (
    EnumAssertionType,
)
from omniclaude.nodes.node_ticket_compiler.models.model_acceptance_criterion import (
    ModelAcceptanceCriterion,
)
from omniclaude.nodes.node_ticket_compiler.models.model_idl_spec import ModelIdlSpec
from omniclaude.nodes.node_ticket_compiler.models.model_policy_envelope import (
    ModelPolicyEnvelope,
)


class ModelCompiledTicket(BaseModel):
    """An executable ticket produced from a single Plan DAG work unit.

    Attributes:
        ticket_id: Stable identifier for this compiled ticket.
        work_unit_id: ID of the source work unit from the Plan DAG.
        dag_id: ID of the Plan DAG that contained the source work unit.
        intent_id: ID of the originating Intent object.
        title: Short human-readable title (becomes the Linear ticket title).
        description: Full ticket description in Markdown.
        idl_spec: Machine-readable IDL: inputs, outputs, side effects.
        acceptance_criteria: Verifiable acceptance criteria (≥1 required).
        policy_envelope: Permission scope and sandbox constraints.
        parent_ticket_id: Optional Linear parent ticket ID (for epics).
        team: Target team name for Linear ticket assignment.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    ticket_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Stable identifier for this compiled ticket",
    )
    work_unit_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="ID of the source work unit from the Plan DAG",
    )
    dag_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="ID of the Plan DAG that contained the source work unit",
    )
    intent_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="ID of the originating Intent object",
    )
    title: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Short ticket title (becomes the Linear ticket title)",
    )
    description: str = Field(
        default="",
        max_length=65_536,
        description="Full ticket description in Markdown",
    )
    idl_spec: ModelIdlSpec = Field(
        ...,
        description="Machine-readable IDL specification",
    )
    acceptance_criteria: tuple[ModelAcceptanceCriterion, ...] = Field(
        ...,
        description="Verifiable acceptance criteria (at least one required)",
    )
    policy_envelope: ModelPolicyEnvelope = Field(
        ...,
        description="Permission scope and sandbox constraints",
    )
    parent_ticket_id: str | None = Field(
        default=None,
        description="Optional Linear parent ticket ID (for epics)",
    )
    team: str = Field(
        default="",
        max_length=256,
        description="Target team name for Linear ticket assignment",
    )

    @model_validator(mode="after")
    def _at_least_one_verifiable_ac(self) -> ModelCompiledTicket:
        """Tickets must have at least one non-MANUAL_VERIFICATION AC."""
        if not self.acceptance_criteria:
            raise ValueError(
                f"Ticket {self.ticket_id!r} has no acceptance criteria — "
                "at least one verifiable AC is required."
            )
        verifiable = [
            ac
            for ac in self.acceptance_criteria
            if ac.assertion_type != EnumAssertionType.MANUAL_VERIFICATION
        ]
        if not verifiable:
            raise ValueError(
                f"Ticket {self.ticket_id!r} has only MANUAL_VERIFICATION ACs — "
                "at least one programmatically verifiable AC is required."
            )
        return self


__all__ = ["ModelCompiledTicket"]
