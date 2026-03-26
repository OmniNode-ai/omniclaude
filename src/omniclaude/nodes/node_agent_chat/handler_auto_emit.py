# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Auto-emit helpers for programmatic chat message broadcasting.

Provides convenience functions for emitting typed chat messages from
hooks, CI watchers, and automation scripts without manual model
construction.

Related tickets:
    - OMN-3972: Agentic Chat Over Kafka MVP
    - OMN-6527: Auto-emit CI_ALERT
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime

from omniclaude.nodes.node_agent_chat.enums.enum_chat_channel import EnumChatChannel
from omniclaude.nodes.node_agent_chat.enums.enum_chat_message_type import (
    EnumChatMessageType,
)
from omniclaude.nodes.node_agent_chat.enums.enum_chat_severity import EnumChatSeverity
from omniclaude.nodes.node_agent_chat.handler_chat_publisher import (
    HandlerChatPublisher,
)
from omniclaude.nodes.node_agent_chat.models.model_chat_message import (
    ModelAgentChatMessage,
)

logger = logging.getLogger(__name__)


def _resolve_session_id() -> str:
    """Resolve the current session ID from environment."""
    return os.environ.get("CLAUDE_SESSION_ID", os.environ.get("SESSION_ID", "unknown"))


def _resolve_agent_id() -> str:
    """Resolve the current agent ID from environment."""
    session_id = _resolve_session_id()
    return os.environ.get("OMNICLAUDE_AGENT_ID", f"auto-{session_id[:8]}")


def emit_ci_alert(
    body: str,
    *,
    severity: EnumChatSeverity = EnumChatSeverity.ERROR,
    ticket_id: str | None = None,
    epic_id: str | None = None,
    publisher: HandlerChatPublisher | None = None,
) -> bool:
    """Emit a CI_ALERT chat message to the CI channel.

    Convenience function for CI watchers and automation hooks. Constructs
    a fully typed ModelAgentChatMessage and publishes via dual-write.

    Args:
        body: Human-readable alert text (e.g., "Build failed on omniclaude#887").
        severity: Alert severity (default ERROR).
        ticket_id: Optional Linear ticket ID for context.
        epic_id: Optional epic ID for scoping.
        publisher: Optional explicit publisher (for testing). If None, creates default.

    Returns:
        True if the file write succeeded.
    """
    pub = publisher or HandlerChatPublisher()
    msg = ModelAgentChatMessage(
        emitted_at=datetime.now(UTC),
        session_id=_resolve_session_id(),
        agent_id=_resolve_agent_id(),
        channel=EnumChatChannel.CI,
        message_type=EnumChatMessageType.CI_ALERT,
        severity=severity,
        body=body,
        ticket_id=ticket_id,
        epic_id=epic_id,
    )
    return pub.publish(msg)


def emit_status(
    body: str,
    *,
    channel: EnumChatChannel = EnumChatChannel.BROADCAST,
    severity: EnumChatSeverity = EnumChatSeverity.INFO,
    epic_id: str | None = None,
    ticket_id: str | None = None,
    publisher: HandlerChatPublisher | None = None,
) -> bool:
    """Emit a STATUS chat message.

    Args:
        body: Status message text.
        channel: Target channel (default BROADCAST).
        severity: Message severity (default INFO).
        epic_id: Optional epic ID.
        ticket_id: Optional ticket ID.
        publisher: Optional explicit publisher (for testing).

    Returns:
        True if the file write succeeded.
    """
    pub = publisher or HandlerChatPublisher()
    msg = ModelAgentChatMessage(
        emitted_at=datetime.now(UTC),
        session_id=_resolve_session_id(),
        agent_id=_resolve_agent_id(),
        channel=channel,
        message_type=EnumChatMessageType.STATUS,
        severity=severity,
        body=body,
        epic_id=epic_id,
        ticket_id=ticket_id,
    )
    return pub.publish(msg)


def emit_progress(
    body: str,
    *,
    epic_id: str | None = None,
    ticket_id: str | None = None,
    publisher: HandlerChatPublisher | None = None,
) -> bool:
    """Emit a PROGRESS chat message to the EPIC channel.

    Args:
        body: Progress update text.
        epic_id: Optional epic ID (auto-scopes to EPIC channel if set).
        ticket_id: Optional ticket ID.
        publisher: Optional explicit publisher (for testing).

    Returns:
        True if the file write succeeded.
    """
    channel = EnumChatChannel.EPIC if epic_id else EnumChatChannel.BROADCAST
    pub = publisher or HandlerChatPublisher()
    msg = ModelAgentChatMessage(
        emitted_at=datetime.now(UTC),
        session_id=_resolve_session_id(),
        agent_id=_resolve_agent_id(),
        channel=channel,
        message_type=EnumChatMessageType.PROGRESS,
        severity=EnumChatSeverity.INFO,
        body=body,
        epic_id=epic_id,
        ticket_id=ticket_id,
    )
    return pub.publish(msg)


__all__ = ["emit_ci_alert", "emit_progress", "emit_status"]
