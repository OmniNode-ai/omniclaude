# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Request model of the Email inbound handler."""

from email.message import EmailMessage

from pydantic import BaseModel, ConfigDict, Field


class ModelEmailInboundRequest(BaseModel):
    """One parsed email to normalize into a channel envelope."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    message: EmailMessage = Field(..., description="Parsed email.message.EmailMessage")
    mailbox: str = Field(
        ...,
        min_length=1,
        description="The mailbox address this was received on (used as channel_id)",
    )
