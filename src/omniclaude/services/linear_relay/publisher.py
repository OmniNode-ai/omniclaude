# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Kafka publisher for the Linear relay service.

Publishes LinearEpicClosedCommand instances to
``onex.cmd.omniclaude.feature-dashboard.v1``.

Uses aiokafka for async publishing within the FastAPI event loop.
The producer is initialized lazily on first use and cleaned up on
application shutdown.

The ``command_id`` is computed here (not in the model) as:
    sha256(f"{org_id}:{epic_id}:closed".encode()).hexdigest()[:16]

See OMN-3502 for specification.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any, Protocol

from omniclaude.services.linear_relay.models import LinearEpicClosedCommand

logger = logging.getLogger(__name__)

# Kafka topic for feature-dashboard commands
FEATURE_DASHBOARD_TOPIC = "onex.cmd.omniclaude.feature-dashboard.v1"  # noqa: arch-topic-naming


class _KafkaProducer(Protocol):
    """Minimal structural protocol for an AIOKafkaProducer."""

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def send_and_wait(
        self,
        topic: str,
        value: Any = None,
        key: Any = None,
    ) -> Any: ...


# Lazy-initialized producer
_producer: _KafkaProducer | None = None


def _get_bootstrap_servers() -> str:
    """Get Kafka bootstrap servers from environment.

    Returns:
        Bootstrap server string. Defaults to ``localhost:19092``
        (local Docker bus, OMN-3431).
    """
    default = "localhost:19092"
    return os.environ.get("KAFKA_BOOTSTRAP_SERVERS", default)


def compute_command_id(org_id: str, epic_id: str) -> str:
    """Compute the idempotency key for a LinearEpicClosedCommand.

    Args:
        org_id: Linear organization ID.
        epic_id: Linear epic (project/initiative) ID.

    Returns:
        First 16 hex characters of
        ``sha256("{org_id}:{epic_id}:closed")``.
    """
    raw = f"{org_id}:{epic_id}:closed".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


async def _get_producer() -> _KafkaProducer:
    """Get or create the Kafka producer (lazy init).

    Returns:
        An initialized ``AIOKafkaProducer`` instance.

    Raises:
        ImportError: If ``aiokafka`` is not installed.
    """
    global _producer  # noqa: PLW0603
    if _producer is None:
        try:
            from aiokafka import AIOKafkaProducer

            producer: _KafkaProducer = AIOKafkaProducer(
                bootstrap_servers=_get_bootstrap_servers(),
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                key_serializer=lambda k: k.encode("utf-8") if k else None,
                request_timeout_ms=5000,
                acks="all",
            )
            await producer.start()
            _producer = producer
            logger.info("Kafka producer started: %s", _get_bootstrap_servers())
        except ImportError:
            logger.error("aiokafka not installed. Install with: uv add aiokafka")
            raise
    return _producer


def build_command(org_id: str, epic_id: str) -> LinearEpicClosedCommand:
    """Build a LinearEpicClosedCommand with a computed command_id.

    Args:
        org_id: Linear organization ID.
        epic_id: Linear epic (project/initiative) ID.

    Returns:
        A ``LinearEpicClosedCommand`` ready for publication.
    """
    command_id = compute_command_id(org_id, epic_id)
    return LinearEpicClosedCommand(
        command_id=command_id,
        org_id=org_id,
        epic_id=epic_id,
    )


async def publish_command(command: LinearEpicClosedCommand) -> None:
    """Publish a LinearEpicClosedCommand to the feature-dashboard topic.

    Args:
        command: The command to publish.

    Raises:
        Exception: If publishing fails after producer initialization.
    """
    producer = await _get_producer()
    # Partition by org_id for ordering guarantees per organisation
    partition_key = command.org_id
    value = command.model_dump(mode="json")

    await producer.send_and_wait(
        FEATURE_DASHBOARD_TOPIC,
        value=value,
        key=partition_key,
    )
    logger.info(
        "Published LinearEpicClosedCommand: org=%s epic=%s command_id=%s message_id=%s",
        command.org_id,
        command.epic_id,
        command.command_id,
        command.message_id,
    )


async def close_producer() -> None:
    """Close the Kafka producer. Call on application shutdown."""
    global _producer  # noqa: PLW0603
    if _producer is not None:
        await _producer.stop()
        _producer = None
        logger.info("Kafka producer closed")
