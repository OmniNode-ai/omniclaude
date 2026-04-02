# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Telegram adapter configuration model."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelTelegramConfig(BaseModel):
    """Configuration for the Telegram channel adapter.

    Bot token is resolved from environment (TELEGRAM_BOT_TOKEN).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    bot_token: str = Field(  # secret-ok: config model, resolved from env at runtime
        ..., min_length=1, description="Telegram bot token from BotFather"
    )
