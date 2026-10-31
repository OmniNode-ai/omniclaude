# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Result model of the Sms outbound handler."""

from pydantic import BaseModel, ConfigDict, Field


class ModelSmsOutboundResult(BaseModel):
    """What the Sms outbound handler did with one reply."""

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    delivered: bool = Field(
        ..., description="True when the reply was handed to the platform"
    )
