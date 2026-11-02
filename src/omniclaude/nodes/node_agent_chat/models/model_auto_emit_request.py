# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The request HandlerAutoEmit.handle takes (OMN-21742).

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.nodes.node_agent_chat.enums.enum_chat_channel import EnumChatChannel
from omniclaude.nodes.node_agent_chat.enums.enum_chat_message_type import (
    EnumChatMessageType,
)
from omniclaude.nodes.node_agent_chat.enums.enum_chat_severity import EnumChatSeverity


class ModelAutoEmitRequest(BaseModel):
    """One CI_ALERT, STATUS or PROGRESS chat message to build and publish.

    ``channel`` and ``severity`` default per message type: CI_ALERT goes to the
    CI channel at ERROR; STATUS goes to BROADCAST at INFO; PROGRESS goes to EPIC
    when ``epic_id`` is set, else BROADCAST, always at INFO.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    message_type: EnumChatMessageType
    body: str = Field(description="Human-readable message text.")
    channel: EnumChatChannel | None = None
    severity: EnumChatSeverity | None = None
    ticket_id: str | None = None
    epic_id: str | None = None
