# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Messaging platform channel type enum for OmniClaw."""

from __future__ import annotations

from enum import StrEnum


class EnumChannelType(StrEnum):
    """Supported messaging platform channel types."""

    DISCORD = "discord"
    SLACK = "slack"
    TELEGRAM = "telegram"
    EMAIL = "email"
    SMS = "sms"
    MATRIX = "matrix"
