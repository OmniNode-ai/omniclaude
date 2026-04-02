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

    bot_token: str = Field(  # secret-ok: config model, resolved from env at runtime
        ..., min_length=1, description="Slack bot OAuth token"
    )
    slack_signing_key: str = (
        Field(  # secret-ok: config model, resolved from env at runtime  # noqa: secrets
            ...,
            min_length=1,
            description="Slack app signing key for webhook verification",
        )
    )
