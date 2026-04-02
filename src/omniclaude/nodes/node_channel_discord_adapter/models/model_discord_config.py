# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Discord adapter configuration model."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelDiscordConfig(BaseModel):
    """Configuration for the Discord channel adapter.

    Bot token is resolved from environment (DISCORD_BOT_TOKEN).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    bot_token: str = Field(..., min_length=1, description="Discord bot token")
    intents_message_content: bool = Field(
        default=True,
        description="Whether to enable the message_content intent",
    )
