# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""NodeAgentChat — Agent chat broadcast subsystem for multi-terminal coordination.

This package provides typed models, enums, and handlers for the agent chat
broadcast system. Messages are dual-written to a local JSONL store and the
Kafka event bus for cross-terminal delivery.

Capability: agent.chat

Exported Components:
    Models:
        ModelAgentChatMessage - Typed domain model for chat messages

    Enums:
        EnumChatChannel - Logical broadcast channels
        EnumChatMessageType - Semantic message types
        EnumChatSeverity - Message severity levels

Example Usage:
    ```python
    from omniclaude.nodes.node_agent_chat import (
        ModelAgentChatMessage,
        EnumChatChannel,
        EnumChatMessageType,
        EnumChatSeverity,
    )

    msg = ModelAgentChatMessage(
        emitted_at=datetime.now(UTC),
        session_id="abc123",
        agent_id="epic-worker-1",
        channel=EnumChatChannel.EPIC,
        message_type=EnumChatMessageType.PROGRESS,
        severity=EnumChatSeverity.INFO,
        body="Completed Wave 1 (3/10 tickets done)",
        epic_id="OMN-3972",
    )
    ```

Related tickets:
    - OMN-3972: Agentic Chat Over Kafka MVP
"""

from .enums import EnumChatChannel, EnumChatMessageType, EnumChatSeverity
from .handler_auto_emit import emit_ci_alert, emit_progress, emit_status
from .handler_chat_publisher import HandlerChatPublisher
from .handler_chat_reader import HandlerChatReader, format_message, format_messages
from .handler_file_chat_store import HandlerFileChatStore
from .models import ModelAgentChatMessage

__all__ = [
    # Models
    "ModelAgentChatMessage",
    # Enums
    "EnumChatChannel",
    "EnumChatMessageType",
    "EnumChatSeverity",
    # Handlers
    "HandlerChatPublisher",
    "HandlerChatReader",
    "HandlerFileChatStore",
    # Auto-emit functions
    "emit_ci_alert",
    "emit_progress",
    "emit_status",
    # Formatting functions
    "format_message",
    "format_messages",
]
