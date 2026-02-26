# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Inbox message model - the versioned envelope for inter-agent messages.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ModelMessageTrace(BaseModel):
    """Trace context embedded in every inter-agent message.

    Attributes:
        correlation_id: End-to-end correlation ID for the workflow.
        run_id: Identifier of the pipeline or epic run that produced the message.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    correlation_id: UUID = Field(
        ...,
        description="End-to-end correlation ID for the workflow",
    )
    run_id: str = Field(
        ...,
        min_length=1,
        description="Pipeline or epic run identifier",
    )


class ModelInboxMessage(BaseModel):
    """Versioned envelope for inter-agent communication.

    Supports two delivery targets:
    - Directed: ``target_agent_id`` is set, message goes to a specific agent inbox.
    - Broadcast: ``target_epic_id`` is set, message goes to the epic status topic.

    Attributes:
        schema_version: Envelope schema version for forward compatibility.
        message_id: Unique identifier for this message (UUID v4).
        emitted_at: Timezone-aware timestamp of when the message was produced.
        trace: Correlation and run context.
        type: Semantic message type (e.g., agent.task.completed, agent.unblock).
        source_agent_id: Identifier of the agent that produced this message.
        target_agent_id: Directed delivery target (mutually exclusive with target_epic_id).
        target_epic_id: Broadcast delivery target (mutually exclusive with target_agent_id).
        payload: Type-specific payload data.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(
        default="1",
        description="Envelope schema version for forward compatibility",
    )
    message_id: UUID = Field(
        ...,
        description="Unique identifier for this message",
    )
    emitted_at: datetime = Field(
        ...,
        description="Timezone-aware timestamp of message production",
    )
    trace: ModelMessageTrace = Field(
        ...,
        description="Correlation and run context",
    )
    type: Literal["agent.task.completed", "agent.unblock"] = Field(
        ...,
        description="Semantic message type",
    )
    source_agent_id: str = Field(
        ...,
        min_length=1,
        description="Identifier of the producing agent",
    )
    target_agent_id: str | None = Field(
        default=None,
        description="Directed delivery target agent (None for broadcast)",
    )
    target_epic_id: str | None = Field(
        default=None,
        description="Broadcast epic target (None for directed)",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Type-specific payload data",
    )

    @field_validator("emitted_at")
    @classmethod
    def _require_timezone_aware(cls, v: datetime) -> datetime:
        """Reject naive datetimes to enforce the explicit-timestamp invariant."""
        if v.tzinfo is None:
            raise ValueError("emitted_at must be timezone-aware (got naive datetime)")
        return v

    @model_validator(mode="after")
    def _require_one_target(self) -> ModelInboxMessage:
        """Ensure exactly one of target_agent_id or target_epic_id is set."""
        if self.target_agent_id is None and self.target_epic_id is None:
            raise ValueError(
                "Exactly one of target_agent_id or target_epic_id must be set"
            )
        if self.target_agent_id is not None and self.target_epic_id is not None:
            raise ValueError(
                "Cannot set both target_agent_id and target_epic_id; "
                "use directed OR broadcast, not both"
            )
        return self


__all__ = ["ModelInboxMessage", "ModelMessageTrace"]
