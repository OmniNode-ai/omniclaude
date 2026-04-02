# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Messaging platform channel type enum for OmniClaw."""

from __future__ import annotations

from enum import Enum


class EnumChannelType(str, Enum):
    """Supported messaging platform channel types."""

    DISCORD = "discord"
    SLACK = "slack"
    TELEGRAM = "telegram"
    EMAIL = "email"
    SMS = "sms"
    MATRIX = "matrix"
