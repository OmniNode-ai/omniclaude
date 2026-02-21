# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Input model for the Ticket Compiler."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ModelTicketCompileRequest(BaseModel):
    """Request to compile a single Plan DAG work unit into a ticket.

    Attributes:
        work_unit_id: ID of the work unit to compile.
        work_unit_title: Title of the work unit.
        work_unit_description: Full description of the work unit.
        work_unit_type: Type of the work unit (EnumWorkUnitType value).
        dag_id: ID of the containing Plan DAG.
        intent_id: ID of the originating Intent object.
        intent_type: Classified intent type string.
        parent_ticket_id: Optional Linear parent ticket ID.
        team: Target team for ticket assignment.
        correlation_id: Correlation UUID for distributed tracing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    work_unit_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="ID of the work unit to compile",
    )
    work_unit_title: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Title of the work unit",
    )
    work_unit_description: str = Field(
        default="",
        max_length=4000,
        description="Full description of the work unit",
    )
    work_unit_type: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Type of the work unit (EnumWorkUnitType value)",
    )
    dag_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="ID of the containing Plan DAG",
    )
    intent_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="ID of the originating Intent object",
    )
    intent_type: str = Field(
        default="",
        max_length=128,
        description="Classified intent type string",
    )
    parent_ticket_id: str | None = Field(
        default=None,
        description="Optional Linear parent ticket ID",
    )
    team: str = Field(
        default="",
        max_length=256,
        description="Target team for ticket assignment",
    )
    correlation_id: UUID = Field(
        ...,
        description="Correlation UUID for distributed tracing",
    )


__all__ = ["ModelTicketCompileRequest"]
