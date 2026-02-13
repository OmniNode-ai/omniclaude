# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Output models for Claude Code hook effect nodes.

This module provides output models for hook effect nodes that publish events
to Kafka. These models represent the result of publishing operations.

Note:
    These models are referenced by the ONEX contract YAML files in the
    contracts/ directory. The actual Kafka publishing implementation
    will be added in OMN-1400.

See Also:
    - src/omniclaude/hooks/contracts/ for ONEX contract definitions
    - src/omniclaude/hooks/schemas.py for event payload models
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelEventPublishResult(BaseModel):
    """Result of publishing an event to Kafka.

    This model represents the outcome of a hook effect node publishing
    an event to the Kafka event bus. It captures delivery metadata for
    observability and error handling.

    Attributes:
        success: Whether the event was successfully published.
        topic: The Kafka topic the event was published to.
        partition: The partition the event was assigned to (if successful).
        offset: The offset within the partition (if successful).
        error_message: Error details if publishing failed.

    Example:
        >>> result = ModelEventPublishResult(
        ...     success=True,
        ...     topic="onex.evt.omniclaude.session-started.v1",
        ...     partition=0,
        ...     offset=12345,
        ... )

    Note:
        The actual publishing implementation will be added in OMN-1400.
        This model is defined here to satisfy the contract YAML references.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        from_attributes=True,
    )

    success: bool = Field(
        ...,
        description="Whether the event was successfully published",
    )
    topic: str = Field(
        ...,
        min_length=1,
        description="The Kafka topic the event was published to",
    )
    partition: int | None = Field(
        default=None,
        ge=0,
        description="The partition the event was assigned to (if successful)",
    )
    offset: int | None = Field(
        default=None,
        ge=0,
        description="The offset within the partition (if successful)",
    )
    error_message: str | None = Field(
        default=None,
        max_length=1000,
        description="Error details if publishing failed",
    )


__all__ = [
    "ModelEventPublishResult",
]
