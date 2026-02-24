# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Linear ticketing result model.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LinearResultStatus(StrEnum):
    """Possible outcomes of a Linear operation."""

    SUCCESS = "success"
    FAILED = "failed"


class ModelLinearResult(BaseModel):
    """Output model for Linear ticketing operation results.

    Attributes:
        operation: The Linear operation that was performed.
        status: Final status of the operation.
        ticket_id: Ticket identifier (populated for ticket_get, ticket_create).
        ticket_url: Ticket URL (populated for ticket_get, ticket_create).
        output: Raw response data as string (e.g., ticket JSON for ticket_get).
        error: Error detail when status is FAILED.
        correlation_id: Correlation ID carried through from the request.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation: str = Field(
        ...,
        description="The Linear operation that was performed",
    )
    status: LinearResultStatus = Field(
        ...,
        description="Final status of the operation",
    )
    ticket_id: str | None = Field(
        default=None,
        description="Ticket identifier (for ticket_get, ticket_create)",
    )
    ticket_url: str | None = Field(
        default=None,
        description="Ticket URL (for ticket_get, ticket_create)",
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


__all__ = ["LinearResultStatus", "ModelLinearResult"]
