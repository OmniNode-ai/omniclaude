# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Inbox delivery result model - output from the agent inbox effect node.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ModelInboxDeliveryResult(BaseModel):
    """Result of an inter-agent message delivery attempt.

    Attributes:
        success: Whether the delivery succeeded on at least one tier.
        message_id: The message ID that was delivered.
        delivery_tier: Which delivery tier succeeded (kafka, standalone, both).
        kafka_delivered: Whether Kafka delivery succeeded.
        standalone_delivered: Whether file-based delivery succeeded.
        topic: The Kafka topic used (None for standalone-only).
        file_path: The file path written (None for kafka-only).
        error: Error message if delivery failed on all tiers.
        duration_ms: Total delivery duration in milliseconds.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    success: bool = Field(
        ...,
        description="Whether the delivery succeeded on at least one tier",
    )
    message_id: UUID = Field(
        ...,
        description="The message ID that was delivered",
    )
    delivery_tier: Literal["kafka", "standalone", "both", "none"] = Field(
        ...,
        description="Which delivery tier(s) succeeded",
    )
    kafka_delivered: bool = Field(
        default=False,
        description="Whether Kafka delivery succeeded",
    )
    standalone_delivered: bool = Field(
        default=False,
        description="Whether file-based delivery succeeded",
    )
    topic: str | None = Field(
        default=None,
        description="Kafka topic used for delivery (None for standalone-only)",
    )
    file_path: str | None = Field(
        default=None,
        description="File path written for standalone delivery (None for kafka-only)",
    )
    error: str | None = Field(
        default=None,
        max_length=1000,
        description="Error message if delivery failed on all tiers",
    )
    duration_ms: float = Field(
        default=0.0,
        ge=0.0,
        description="Total delivery duration in milliseconds",
    )


__all__ = ["ModelInboxDeliveryResult"]
