# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Vendor-agnostic ticketing result model.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TicketingResultStatus(StrEnum):
    """Possible outcomes of a ticketing operation."""

    SUCCESS = "success"
    FAILED = "failed"


class ModelTicketingResult(BaseModel):
    """Output model for vendor-agnostic ticketing operation results.

    Attributes:
        operation: The ticketing operation that was performed.
        status: Final status of the operation.
        ticket_id: Ticket identifier (if applicable).
        ticket_url: Ticket URL (if applicable).
        output: Raw response data as string.
        error: Error detail when status is FAILED.
        correlation_id: Correlation ID carried through from the request.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation: str = Field(
        ...,
        description="The ticketing operation that was performed",
    )
    status: TicketingResultStatus = Field(
        ...,
        description="Final status of the operation",
    )
    ticket_id: str | None = Field(
        default=None,
        description="Ticket identifier (if applicable)",
    )
    ticket_url: str | None = Field(
        default=None,
        description="Ticket URL (if applicable)",
    )
    output: str | None = Field(
        default=None,
        description="Raw response data as string",
    )
    error: str | None = Field(
        default=None,
        description="Error detail when status is FAILED",
    )
    correlation_id: UUID | None = Field(
        default=None,
        description="Correlation ID carried through from the request",
    )


__all__ = ["TicketingResultStatus", "ModelTicketingResult"]
