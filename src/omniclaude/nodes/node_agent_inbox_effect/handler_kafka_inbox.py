# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Handler for Kafka-based agent inbox delivery (EVENT_BUS+ tier).

Implements ProtocolAgentInbox by delegating to the emit daemon's
``emit_event`` function for Kafka message production.

Topic Mapping:
    Directed messages:
        onex.evt.omniclaude.agent-inbox.{agent_id}.v1
    Broadcast messages:
        onex.evt.omniclaude.epic.{epic_id}.status.v1

Partition key is always agent_id for directed messages and epic_id for
broadcast messages, ensuring per-agent and per-epic ordering.

Design Decisions:
    - Constructor injection for ``emit_fn`` keeps plugins/ off the import path
    - Fallback dynamic import of ``emit_client_wrapper.emit_event`` supports
      hook-script contexts where the module is on ``sys.path``
    - No-op emitter when daemon is unavailable preserves the "hooks never block"
      invariant

.. versionadded:: 1.0.0
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import datetime
from typing import Final

from omniclaude.nodes.node_agent_inbox_effect.models import (
    ModelInboxDeliveryResult,
    ModelInboxMessage,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Topic template for directed agent inbox messages.
TOPIC_DIRECTED_TEMPLATE: Final[str] = "onex.evt.omniclaude.agent-inbox.{agent_id}.v1"

#: Topic template for epic broadcast status messages.
TOPIC_BROADCAST_TEMPLATE: Final[str] = "onex.evt.omniclaude.epic.{epic_id}.status.v1"

#: Semantic event type for agent inbox messages.
EVENT_TYPE_AGENT_INBOX: Final[str] = "agent.inbox"

# ---------------------------------------------------------------------------
# Emit function type alias
# ---------------------------------------------------------------------------

#: Signature: ``(event_type: str, payload: dict[str, object]) -> bool``
EmitFn = Callable[[str, dict[str, object]], bool]


def _noop_emit(event_type: str, payload: dict[str, object]) -> bool:
    """No-op emitter used when the daemon is unavailable."""
    return False


def _resolve_default_emit_fn() -> EmitFn:
    """Try to import ``emit_event`` from the emit client wrapper.

    Returns:
        The resolved emit function, or :func:`_noop_emit` on failure.
    """
    try:
        from emit_client_wrapper import emit_event

        logger.debug("Resolved emit_event from emit_client_wrapper")
        return emit_event  # type: ignore[no-any-return]
    except ImportError:
        logger.warning(
            "emit_client_wrapper not on sys.path; "
            "agent inbox Kafka delivery will be no-op until an emit_fn is injected"
        )
        return _noop_emit


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class HandlerKafkaInbox:
    """Kafka-based agent inbox handler (EVENT_BUS+ tier).

    Implements ``ProtocolAgentInbox`` by delegating to the emit daemon
    for Kafka message production with partition-ordered delivery.

    Args:
        emit_fn: Optional callable with signature
            ``(event_type: str, payload: dict[str, object]) -> bool``.
            When *None*, the handler attempts a dynamic import of
            ``emit_event`` from ``emit_client_wrapper``; if that fails
            a no-op emitter is used.

    Example::

        # With explicit injection (preferred in tests)
        handler = HandlerKafkaInbox(emit_fn=mock_emit)

        # With auto-resolved default (hook-script context)
        handler = HandlerKafkaInbox()
    """

    def __init__(self, emit_fn: EmitFn | None = None) -> None:
        self._emit_fn: EmitFn = (
            emit_fn if emit_fn is not None else _resolve_default_emit_fn()
        )

    # -- ProtocolAgentInbox interface ----------------------------------------

    @property
    def handler_key(self) -> str:
        """Backend identifier for handler routing."""
        return "kafka"

    async def send_message(
        self,
        message: ModelInboxMessage,
    ) -> ModelInboxDeliveryResult:
        """Deliver a message to the appropriate Kafka topic.

        Directed messages go to agent-specific topics; broadcast messages
        go to epic-wide status topics.

        Args:
            message: The inbox message envelope to deliver.

        Returns:
            ModelInboxDeliveryResult with Kafka delivery status.
        """
        start = time.monotonic()

        try:
            topic = self._resolve_topic(message)
            payload = self._build_payload(message)

            emitted = await asyncio.to_thread(
                self._emit_fn, EVENT_TYPE_AGENT_INBOX, payload
            )
            elapsed_ms = (time.monotonic() - start) * 1000.0

            if emitted:
                return ModelInboxDeliveryResult(
                    success=True,
                    message_id=message.message_id,
                    delivery_tier="kafka",
                    kafka_delivered=True,
                    standalone_delivered=False,
                    topic=topic,
                    file_path=None,
                    error=None,
                    duration_ms=elapsed_ms,
                )

            return ModelInboxDeliveryResult(
                success=False,
                message_id=message.message_id,
                delivery_tier="none",
                kafka_delivered=False,
                standalone_delivered=False,
                topic=topic,
                file_path=None,
                error="Emit daemon returned failure (daemon unavailable or dropped)",
                duration_ms=elapsed_ms,
            )

        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000.0
            error_msg = f"{type(exc).__name__}: {exc}"
            logger.debug("Kafka inbox delivery failed: %s", error_msg)

            return ModelInboxDeliveryResult(
                success=False,
                message_id=message.message_id,
                delivery_tier="none",
                kafka_delivered=False,
                standalone_delivered=False,
                topic=None,
                file_path=None,
                error=error_msg[:1000],
                duration_ms=elapsed_ms,
            )

    async def receive_messages(
        self,
        agent_id: str,
        since: datetime | None = None,
    ) -> list[ModelInboxMessage]:
        """Kafka consumer-based message reception is not yet implemented.

        The EVENT_BUS+ tier currently uses a push model via Kafka consumers
        that are set up at the infrastructure level. This method returns an
        empty list; use the STANDALONE handler for pull-based message reading.

        Args:
            agent_id: The agent whose inbox to read.
            since: Only return messages emitted after this timestamp.

        Returns:
            Empty list (Kafka reception is push-based, not pull-based).
        """
        logger.debug(
            "Kafka receive_messages is a no-op; use STANDALONE handler for pull-based reads"
        )
        return []

    async def gc_inbox(
        self,
        ttl_hours: int = 24,
    ) -> int:
        """No-op for Kafka tier (Kafka handles its own retention).

        Args:
            ttl_hours: Ignored for Kafka backend.

        Returns:
            Always 0 (Kafka manages its own topic retention).
        """
        return 0

    # -- Internal helpers ----------------------------------------------------

    @staticmethod
    def _resolve_topic(message: ModelInboxMessage) -> str:
        """Resolve the Kafka topic for a message.

        Args:
            message: The message to route.

        Returns:
            The resolved topic string.
        """
        if message.target_agent_id is not None:
            return TOPIC_DIRECTED_TEMPLATE.format(agent_id=message.target_agent_id)
        if message.target_epic_id is not None:
            return TOPIC_BROADCAST_TEMPLATE.format(epic_id=message.target_epic_id)
        raise ValueError("Message must have target_agent_id or target_epic_id")

    @staticmethod
    def _build_payload(message: ModelInboxMessage) -> dict[str, object]:
        """Build the event payload for the emit daemon.

        Args:
            message: The inbox message.

        Returns:
            Dictionary payload ready for the emit daemon.
        """
        return {
            "schema_version": message.schema_version,
            "message_id": str(message.message_id),
            "emitted_at": message.emitted_at.isoformat(),
            "trace": {
                "correlation_id": str(message.trace.correlation_id),
                "run_id": message.trace.run_id,
            },
            "type": message.type,
            "source_agent_id": message.source_agent_id,
            "target_agent_id": message.target_agent_id,
            "target_epic_id": message.target_epic_id,
            "payload": message.payload,
        }


__all__ = [
    "EVENT_TYPE_AGENT_INBOX",
    "EmitFn",
    "HandlerKafkaInbox",
    "TOPIC_BROADCAST_TEMPLATE",
    "TOPIC_DIRECTED_TEMPLATE",
]
