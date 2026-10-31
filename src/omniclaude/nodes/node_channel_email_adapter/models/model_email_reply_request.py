# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Request and result models of the Email outbound handler."""

from email.message import EmailMessage

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.nodes.node_channel_reply_dispatcher.models.model_channel_reply import (
    ModelChannelReply,
)


class ModelEmailReplyRequest(BaseModel):
    """One channel reply to build into an outgoing email."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reply: ModelChannelReply = Field(..., description="The channel reply to send")
    from_addr: str = Field(..., description="Sender email address")
    to_addr: str = Field(..., description="Recipient email address")
    subject: str = Field(default="", description="Email subject line")


class ModelEmailReplyResult(BaseModel):
    """The outgoing email, built and ready to send."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    message: EmailMessage = Field(..., description="Constructed EmailMessage")
