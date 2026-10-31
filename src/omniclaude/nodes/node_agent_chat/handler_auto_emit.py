# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Auto-emit handler for programmatic chat message broadcasting.

HandlerAutoEmit.handle builds and publishes a typed chat message (CI_ALERT,
STATUS or PROGRESS) from hooks, CI watchers, and automation scripts without
manual model construction.

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
from omniclaude.nodes.node_agent_chat.models.model_auto_emit_request import (
    ModelAutoEmitRequest,
)
from omniclaude.nodes.node_agent_chat.models.model_auto_emit_result import (
    ModelAutoEmitResult,
)
from omniclaude.nodes.node_agent_chat.models.model_chat_message import (
    ModelAgentChatMessage,
)

logger = logging.getLogger(__name__)


def _resolve_session_id() -> str:
    from plugins.onex.hooks.lib.session_id import resolve_session_id

    return resolve_session_id()


def _resolve_agent_id() -> str:
    """Resolve the current agent ID from environment."""
    session_id = _resolve_session_id()
    return os.environ.get("OMNICLAUDE_AGENT_ID", f"auto-{session_id[:8]}")


class HandlerAutoEmit:
    """Build a typed chat message from a request and publish it via dual-write.

    Args:
        publisher: Optional explicit publisher (for testing). If None, creates default.
    """

    def __init__(self, publisher: HandlerChatPublisher | None = None) -> None:
        self._publisher = publisher

    def handle(self, request: ModelAutoEmitRequest) -> ModelAutoEmitResult:
        """Emit the CI_ALERT, STATUS or PROGRESS message the request names."""
        channel, severity = self._defaults(request)
        pub = self._publisher or HandlerChatPublisher()
        msg = ModelAgentChatMessage(
            emitted_at=datetime.now(UTC),
            session_id=_resolve_session_id(),
            agent_id=_resolve_agent_id(),
            channel=channel,
            message_type=request.message_type,
            severity=severity,
            body=request.body,
            ticket_id=request.ticket_id,
            epic_id=request.epic_id,
        )
        return ModelAutoEmitResult(published=pub.publish(msg))

    @staticmethod
    def _defaults(
        request: ModelAutoEmitRequest,
    ) -> tuple[EnumChatChannel, EnumChatSeverity]:
        if request.message_type is EnumChatMessageType.CI_ALERT:
            return (
                request.channel or EnumChatChannel.CI,
                request.severity or EnumChatSeverity.ERROR,
            )
        if request.message_type is EnumChatMessageType.PROGRESS:
            channel = (
                EnumChatChannel.EPIC if request.epic_id else EnumChatChannel.BROADCAST
            )
            return channel, EnumChatSeverity.INFO
        return (
            request.channel or EnumChatChannel.BROADCAST,
            request.severity or EnumChatSeverity.INFO,
        )


__all__ = ["HandlerAutoEmit"]
