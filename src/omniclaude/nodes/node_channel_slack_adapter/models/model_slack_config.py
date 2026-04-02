# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Slack adapter configuration model."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelSlackConfig(BaseModel):
    """Configuration for the Slack channel adapter.

    Credentials are resolved from environment at runtime.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    bot_token: str = Field(  # secret-ok: resolved from env
        ..., min_length=1, description="Slack bot OAuth token"
    )
    app_verification: str = Field(  # secret-ok: resolved from env
        ..., min_length=1, description="Slack signing verification value"
    )
