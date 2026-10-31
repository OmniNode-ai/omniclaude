# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Result model of the Discord outbound handler."""

from pydantic import BaseModel, ConfigDict, Field


class ModelDiscordOutboundResult(BaseModel):
    """What the Discord outbound handler did with one reply."""

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    delivered: bool = Field(
        ..., description="True when the reply was handed to the platform"
    )
