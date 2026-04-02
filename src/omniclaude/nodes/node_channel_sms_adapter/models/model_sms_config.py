# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""SMS adapter configuration model."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelSmsConfig(BaseModel):
    """Configuration for the SMS/Twilio channel adapter.

    Credentials are resolved from environment at runtime.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_sid: str = Field(  # secret-ok: config model, resolved from env at runtime
        ..., min_length=1, description="Twilio account SID"
    )
    auth_token: str = Field(  # secret-ok: config model, resolved from env at runtime
        ..., min_length=1, description="Twilio auth token"
    )
    phone_number: str = Field(
        ..., min_length=1, description="Twilio phone number for sending"
    )
