# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Linear ticketing request model.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LinearOperation(StrEnum):
    """Supported Linear ticketing operations."""

    TICKET_GET = "ticket_get"
    TICKET_UPDATE_STATUS = "ticket_update_status"
    TICKET_ADD_COMMENT = "ticket_add_comment"
    TICKET_CREATE = "ticket_create"


class ModelLinearRequest(BaseModel):
    """Input model for Linear ticketing operation requests.

    Attributes:
        operation: The Linear operation to perform.
        ticket_id: Linear ticket identifier (e.g., 'OMN-1234').
        status: New status for ticket_update_status.
        comment_body: Comment body for ticket_add_comment (Markdown).
        title: Ticket title for ticket_create.
        description: Ticket description for ticket_create (Markdown).
        team_id: Linear team ID for ticket_create.
        correlation_id: Correlation ID for tracing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation: LinearOperation = Field(
        ...,
        description="The Linear operation to perform",
    )
    ticket_id: str | None = Field(
        default=None,
        description="Linear ticket identifier (e.g., 'OMN-1234')",
    )
    status: str | None = Field(
        default=None,
        description="New status for ticket_update_status",
    )
    comment_body: str | None = Field(
        default=None,
        description="Comment body for ticket_add_comment (Markdown)",
    )
    title: str | None = Field(
        default=None,
        description="Ticket title for ticket_create",
    )
    description: str | None = Field(
        default=None,
        description="Ticket description for ticket_create (Markdown)",
    )
    team_id: str | None = Field(
        default=None,
        description="Linear team ID for ticket_create",
    )
    correlation_id: UUID | None = Field(
        default=None,
        description="Correlation ID for tracing",
    )


__all__ = ["LinearOperation", "ModelLinearRequest"]
