# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Routing request model — input to the NodeAgentRouter node.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ModelAgentRouterRequest(BaseModel):
    """Input to the NodeAgentRouter compute node.

    Wraps the arguments accepted by AgentRouter.route().

    Attributes:
        user_request: User's input text to route.
        context: Optional execution context (domain, previous agent, etc.).
        max_recommendations: Maximum number of recommendations to return.
        correlation_id: Optional correlation ID for request tracing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    user_request: str = Field(
        ...,
        min_length=1,
        max_length=50_000,
        description="User's input text to route",
    )
    context: dict[str, Any] | None = Field(  # any-ok: caller-supplied context bag
        default=None,
        description="Optional execution context (domain, previous agent, etc.)",
    )
    max_recommendations: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum number of recommendations to return",
    )
    correlation_id: UUID | None = Field(
        default=None,
        description="Optional correlation ID for request tracing",
    )


__all__ = ["ModelAgentRouterRequest"]
