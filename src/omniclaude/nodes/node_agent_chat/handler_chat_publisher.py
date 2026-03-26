# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Dual-write chat publisher — persists to file store AND emits to Kafka.

The publisher implements the dual-write pattern:
1. Append to local JSONL file (always succeeds if disk is available).
2. Emit to Kafka via the emit daemon (best-effort; failure does not block).

This ordering ensures local persistence is the source of truth while
Kafka provides cross-terminal fan-out.

Related tickets:
    - OMN-3972: Agentic Chat Over Kafka MVP
    - OMN-6510: Dual-write publisher
"""

from __future__ import annotations

import logging

from omniclaude.nodes.node_agent_chat.handler_file_chat_store import (
    HandlerFileChatStore,
)
from omniclaude.nodes.node_agent_chat.models.model_chat_message import (
    ModelAgentChatMessage,
)

logger = logging.getLogger(__name__)

# Event type registered in emit_client_wrapper.py SUPPORTED_EVENT_TYPES
_EMIT_EVENT_TYPE = "agent.chat.broadcast"


def _emit_to_kafka(message: ModelAgentChatMessage) -> bool:
    """Best-effort emit to Kafka via the emit daemon.

    Returns True if the event was queued, False otherwise.
    Import is deferred to avoid hard dependency on the emit daemon
    in test environments.
    """
    try:
        # Deferred import: emit_client_wrapper lives in plugins/onex/hooks/lib/
        # and may not be on sys.path in all contexts. The import path
        # 'emit_client_wrapper' works because plugins/onex/hooks/lib/ is
        # added to sys.path by the hook framework.
        from emit_client_wrapper import emit_event  # type: ignore[import-not-found]

        payload = {
            "message_id": str(message.message_id),
            "session_id": message.session_id,
            "agent_id": message.agent_id,
            "channel": message.channel.value,
            "message_type": message.message_type.value,
            "severity": message.severity.value,
            "body": message.body,
            "epic_id": message.epic_id,
            "correlation_id": str(message.correlation_id)
            if message.correlation_id
            else None,
            "ticket_id": message.ticket_id,
            "emitted_at": message.emitted_at.isoformat(),
            "schema_version": message.schema_version,
            "metadata": message.metadata,
        }
        return emit_event(_EMIT_EVENT_TYPE, payload)
    except ImportError:
        logger.debug("emit_client_wrapper not available; Kafka emit skipped")
        return False
    except (OSError, RuntimeError) as exc:
        logger.warning("Kafka emit failed for chat message: %s", exc)
        return False


class HandlerChatPublisher:
    """Dual-write publisher: file store + Kafka emit daemon.

    Attributes:
        store: The underlying file-based chat store.
    """

    __slots__ = ("_store",)

    def __init__(self, store: HandlerFileChatStore | None = None) -> None:
        """Initialize the publisher.

        Args:
            store: Explicit file store instance. If None, a default store
                   is created (uses $ONEX_STATE_DIR/chat/chat.jsonl).
        """
        self._store = store or HandlerFileChatStore()

    @property
    def store(self) -> HandlerFileChatStore:
        """The underlying file store."""
        return self._store

    def publish(self, message: ModelAgentChatMessage) -> bool:
        """Persist message to file and emit to Kafka.

        File write is always attempted first (source of truth).
        Kafka emit is best-effort (failure logged, not raised).

        Args:
            message: The chat message to publish.

        Returns:
            True if the file write succeeded (Kafka status is independent).

        Raises:
            OSError: If the file write fails (disk full, permissions, etc.).
        """
        # Step 1: Persist to local file (always)
        self._store.append(message)

        # Step 2: Best-effort Kafka emit
        kafka_ok = _emit_to_kafka(message)
        if not kafka_ok:
            logger.debug(
                "Kafka emit skipped/failed for message_id=%s; file store is authoritative",
                message.message_id,
            )

        return True


__all__ = ["HandlerChatPublisher"]
