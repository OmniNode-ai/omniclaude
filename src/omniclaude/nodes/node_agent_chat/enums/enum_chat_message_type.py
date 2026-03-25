# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Enum for chat message semantic types.

Each type classifies the intent of a chat message, enabling downstream
consumers to filter, route, or render messages differently.
"""

from __future__ import annotations

from enum import Enum


class EnumChatMessageType(str, Enum):
    """Semantic classification of agent chat messages.

    Attributes:
        STATUS: Agent reporting its current state (started, idle, blocked).
        PROGRESS: Incremental progress update on a task.
        CI_ALERT: CI/CD pipeline event (build failure, test regression, deploy).
        COORDINATION: Inter-agent coordination (handoff, dependency signal).
        HUMAN: Human-authored message injected via /chat skill.
        SYSTEM: Platform-generated announcement (not from any agent session).
    """

    STATUS = "STATUS"
    PROGRESS = "PROGRESS"
    CI_ALERT = "CI_ALERT"
    COORDINATION = "COORDINATION"
    HUMAN = "HUMAN"
    SYSTEM = "SYSTEM"


__all__ = ["EnumChatMessageType"]
