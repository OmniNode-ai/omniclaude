# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Kafka publisher for the CI relay service.

Publishes PRStatusEvent instances to the configured Kafka bootstrap servers.
Uses aiokafka for async publishing within the FastAPI event loop.

The publisher is initialized lazily on first use and cleaned up on
application shutdown.
"""

from __future__ import annotations

import json
import logging
import os

from omniclaude.services.ci_relay.models import PRStatusEvent

logger = logging.getLogger(__name__)

# Lazy-initialized producer
_producer: object | None = None


def _get_bootstrap_servers() -> str:
    """Get Kafka bootstrap servers from environment.

    Returns:
        Bootstrap server string. Defaults to localhost:29092 for development.
    """
    return os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "192.168.86.200:29092")


async def _get_producer() -> object:
    """Get or create the Kafka producer.

    Returns:
        An initialized AIOKafkaProducer instance.

    Raises:
        ImportError: If aiokafka is not installed.
    """
    global _producer  # noqa: PLW0603
    if _producer is None:
        try:
            from aiokafka import AIOKafkaProducer

            _producer = AIOKafkaProducer(
                bootstrap_servers=_get_bootstrap_servers(),
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                key_serializer=lambda k: k.encode("utf-8") if k else None,
                request_timeout_ms=5000,
                acks="all",
            )
            await _producer.start()  # type: ignore[union-attr]
            logger.info("Kafka producer started: %s", _get_bootstrap_servers())
        except ImportError:
            logger.error("aiokafka not installed. Install with: uv add aiokafka")
            raise
    return _producer


async def publish_event(topic: str, event: PRStatusEvent) -> None:
    """Publish a PRStatusEvent to a Kafka topic.

    Args:
        topic: Kafka topic name.
        event: The event to publish.

    Raises:
        Exception: If publishing fails after producer initialization.
    """
    producer = await _get_producer()
    # Partition by repo for ordering guarantees per-repo
    partition_key = event.repo
    value = event.model_dump(mode="json")

    await producer.send_and_wait(  # type: ignore[union-attr]
        topic,
        value=value,
        key=partition_key,
    )
    logger.debug(
        "Published to %s: key=%s message_id=%s",
        topic,
        partition_key,
        event.message_id,
    )


async def close_producer() -> None:
    """Close the Kafka producer. Call on application shutdown."""
    global _producer  # noqa: PLW0603
    if _producer is not None:
        await _producer.stop()  # type: ignore[union-attr]
        _producer = None
        logger.info("Kafka producer closed")
