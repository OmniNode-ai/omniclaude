# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Request model of the SMS/Twilio inbound handler."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelSmsWebhookRequest(BaseModel):
    """A Twilio SMS webhook form body, read by Twilio's own field names.

    Twilio sends many more fields than the handler uses; the rest are ignored.
    """

    model_config = ConfigDict(frozen=True, extra="ignore", populate_by_name=True)

    message_sid: str | None = Field(
        default=None, alias="MessageSid", description="Twilio message SID"
    )
    from_number: str = Field(default="", alias="From", description="Sender number")
    to_number: str = Field(default="", alias="To", description="Receiving number")
    body: str = Field(default="", alias="Body", description="Message text")
    from_city: str | None = Field(
        default=None, alias="FromCity", description="Sender city, if Twilio sent one"
    )
