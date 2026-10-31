# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Result model of the Email inbound handler."""

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.shared.models.model_channel_envelope import ModelChannelEnvelope


class ModelEmailInboundResult(BaseModel):
    """What the Email inbound handler made of one message.

    ``envelope`` is ``None`` when the handler skips the message.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    envelope: ModelChannelEnvelope | None = Field(
        default=None,
        description="Normalized envelope, or None when the message is skipped",
    )
