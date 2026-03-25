# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Enum for chat broadcast channels.

Each channel represents a logical grouping of chat messages that agents
can subscribe to. The BROADCAST channel is the default for all agents;
other channels scope messages to specific contexts.
"""

from __future__ import annotations

from enum import Enum


class EnumChatChannel(str, Enum):
    """Logical channels for agent chat message routing.

    Attributes:
        BROADCAST: All-agents channel. Every session receives these messages.
        EPIC: Scoped to a specific epic run. Messages include epic_id for filtering.
        CI: Continuous integration alerts (build failures, test regressions).
        SYSTEM: Platform-level announcements (infra status, deploy events).
    """

    BROADCAST = "BROADCAST"
    EPIC = "EPIC"
    CI = "CI"
    SYSTEM = "SYSTEM"


__all__ = ["EnumChatChannel"]
