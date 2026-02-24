# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Vendor-agnostic ticketing request model.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TicketingOperation(StrEnum):
    """Supported ticketing operations (vendor-agnostic)."""

    TICKET_GET = "ticket_get"
    TICKET_UPDATE_STATUS = "ticket_update_status"
    TICKET_ADD_COMMENT = "ticket_add_comment"


class ModelTicketingRequest(BaseModel):
    """Input model for vendor-agnostic ticketing operation requests.

    This is the base model used with NodeTicketingEffect when the caller
    is vendor-agnostic. For Linear-specific operations, use ModelLinearRequest
    with NodeLinearEffect.

    Attributes:
        operation: The ticketing operation to perform.
        ticket_id: Ticket identifier (vendor-native format).
        status: New status for ticket_update_status.
        comment_body: Comment body for ticket_add_comment (Markdown).
        correlation_id: Correlation ID for tracing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation: TicketingOperation = Field(
        ...,
        description="The ticketing operation to perform",
    )
    ticket_id: str | None = Field(
        default=None,
        description="Ticket identifier (vendor-native format)",
    )
    status: str | None = Field(
        default=None,
        description="New status for ticket_update_status",
    )
    comment_body: str | None = Field(
        default=None,
        description="Comment body for ticket_add_comment (Markdown)",
    )
    correlation_id: UUID | None = Field(
        default=None,
        description="Correlation ID for tracing",
    )


__all__ = ["TicketingOperation", "ModelTicketingRequest"]
