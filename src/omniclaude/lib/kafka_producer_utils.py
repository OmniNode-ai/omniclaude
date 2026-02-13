#!/usr/bin/env python3
"""
Shared Kafka Producer Utilities

Shared utility functions used by transformation_event_publisher.py and
manifest_injection_event_publisher.py. Eliminates duplication of Kafka
configuration, envelope creation, and producer lifecycle management.

DESIGN RULE: Non-Blocking Event Emission
=========================================
Event emission is BEST-EFFORT, NEVER blocks execution.
"""

import asyncio
import json
import logging
import os
import threading
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from omniclaude.hooks.topics import build_topic

logger = logging.getLogger(__name__)

# Kafka publish timeout (10 seconds)
KAFKA_PUBLISH_TIMEOUT_SECONDS = 10.0


def get_kafka_bootstrap_servers() -> str | None:
    """
    Get Kafka bootstrap servers from environment.

    Per CLAUDE.md: No localhost defaults - explicit configuration required.

    Returns:
        Bootstrap servers string, or None if not configured.
    """
    servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS")
    if not servers:
        logger.warning(
            "KAFKA_BOOTSTRAP_SERVERS not set. Kafka publishing disabled. "
            "Set KAFKA_BOOTSTRAP_SERVERS environment variable to enable event publishing."
        )
        return None
    return servers


def create_event_envelope(
    event_type_value: str,
    event_type_name: str,
    payload: dict[str, Any],
    correlation_id: str,
    schema_domain: str,
    source: str = "omniclaude",
    tenant_id: str = "default",
    namespace: str = "onex",
    causation_id: str | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """
    Create OnexEnvelopeV1 standard event envelope.

    Args:
        event_type_value: Event type string value (e.g., from enum.value for Kafka topic)
        event_type_name: Event type name for schema_ref (e.g., "started", "completed", "failed")
        payload: Event payload data
        correlation_id: Correlation ID for distributed tracing
        schema_domain: Domain for schema_ref (e.g., "transformation", "manifest-injection")
        source: Source service name (default: omniclaude)
        tenant_id: Tenant identifier (default: default)
        namespace: Event namespace (default: onex)
        causation_id: Optional causation ID for event chains
        timestamp: Explicit timestamp (ISO 8601). If None, uses datetime.now(UTC).

    Returns:
        Dict containing OnexEnvelopeV1 wrapped event
    """
    return {
        "event_type": event_type_value,
        "event_id": str(uuid4()),
        "timestamp": timestamp or datetime.now(UTC).isoformat(),
        "tenant_id": tenant_id,
        "namespace": namespace,
        "source": source,
        "correlation_id": correlation_id,
        "causation_id": causation_id,
        "schema_ref": f"registry://{namespace}/{schema_domain}/{event_type_name}/v1",
        "payload": payload,
    }


def build_kafka_topic(topic_base_value: str) -> str:
    """Build Kafka topic name from TopicBase value.

    Topics are realm-agnostic per OMN-1972: TopicBase values ARE the wire
    topic names. No environment prefix is applied.

    Args:
        topic_base_value: Base topic name from TopicBase enum

    Returns:
        Topic name (same as input since prefix is empty)
    """
    return build_topic("", topic_base_value)


class KafkaProducerManager:
    """
    Manages a lazy-loaded Kafka producer singleton with proper async locking.

    Each publisher module creates its own KafkaProducerManager instance,
    but the shared logic for producer creation, locking, and cleanup is
    centralized here.
    """

    def __init__(self, name: str = "default") -> None:
        self._name = name
        self._producer: Any | None = None
        self._producer_loop: asyncio.AbstractEventLoop | None = None
        self._lock: asyncio.Lock | None = None
        self._lock_loop: asyncio.AbstractEventLoop | None = None
        self._lock_creation_lock = threading.Lock()

    async def get_lock(self) -> asyncio.Lock:
        """Get or create the producer lock lazily under a running event loop.

        Thread-safe via double-checked locking. The lock is bound to the
        event loop that created it; a new lock is created if the loop changes.
        """
        current_loop = asyncio.get_running_loop()
        if self._lock is not None and self._lock_loop is current_loop:
            return self._lock
        with self._lock_creation_lock:
            if self._lock is None or self._lock_loop is not current_loop:
                self._lock = asyncio.Lock()
                self._lock_loop = current_loop
        return self._lock

    async def get_producer(self) -> Any | None:
        """Get or create Kafka producer (async singleton pattern).

        AIOKafkaProducer is bound to the event loop it was started in.
        If the loop changes (e.g., sync wrappers calling asyncio.run()),
        the cached producer is invalidated to prevent stale-loop errors.
        """
        current_loop = asyncio.get_running_loop()
        if self._producer is not None:
            if self._producer_loop is current_loop:
                return self._producer
            # Loop changed - invalidate stale producer
            logger.debug(
                "Event loop changed, invalidating stale Kafka producer [%s]",
                self._name,
            )
            self._producer = None
            self._producer_loop = None

        async with await self.get_lock():
            current_producer = cast("Any | None", self._producer)
            if current_producer is not None:
                return current_producer

            try:
                from aiokafka import AIOKafkaProducer

                bootstrap_servers = get_kafka_bootstrap_servers()
                if bootstrap_servers is None:
                    return None

                producer = AIOKafkaProducer(
                    bootstrap_servers=bootstrap_servers,
                    value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                    compression_type="gzip",
                    linger_ms=10,
                    acks=1,
                    max_batch_size=16384,
                    request_timeout_ms=5000,
                )

                await producer.start()
                self._producer = producer
                self._producer_loop = asyncio.get_running_loop()
                logger.info(
                    "Kafka producer [%s] initialized: %s",
                    self._name,
                    bootstrap_servers,
                )
                return producer

            except ImportError:
                logger.warning(
                    "aiokafka not installed. Events will not be published. "
                    "Install with: pip install aiokafka>=0.9.0"
                )
                return None
            except Exception as e:
                logger.warning(
                    f"Failed to initialize Kafka producer [{self._name}]: {e}"
                )
                return None

    async def close(self) -> None:
        """Close Kafka producer."""
        if self._producer is not None:
            try:
                await self._producer.stop()
                logger.info(f"Kafka producer [{self._name}] closed")
            except Exception as e:
                logger.warning(
                    f"Error closing Kafka producer [{self._name}]: {e}"
                )
            finally:
                self._producer = None

    def cleanup_sync(self) -> None:
        """Synchronous cleanup for atexit handler."""
        if self._producer is None:
            return

        try:
            try:
                asyncio.get_running_loop()
                return  # Loop running, can't cleanup synchronously
            except RuntimeError:
                pass

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(self.close())
            except Exception:
                pass
            finally:
                loop.close()

            if self._producer is not None:
                try:
                    client = getattr(self._producer, "_client", None)
                    if client is not None:
                        close_method = getattr(client, "close", None)
                        if close_method is not None and callable(close_method):
                            close_method()
                    self._producer = None
                except (AttributeError, TypeError):
                    self._producer = None
                except Exception:
                    self._producer = None

        except Exception:
            self._producer = None

    async def publish(
        self,
        envelope: dict[str, Any],
        topic_base_value: str,
        partition_key: str,
    ) -> bool:
        """Publish an event envelope to Kafka.

        Args:
            envelope: OnexEnvelopeV1 wrapped event
            topic_base_value: Base topic name from TopicBase enum
            partition_key: Partition key for ordering (usually correlation_id)

        Returns:
            True if published successfully, False otherwise
        """
        try:
            producer = await self.get_producer()
            if producer is None:
                logger.debug("Kafka producer unavailable, event not published")
                return False

            topic = build_kafka_topic(topic_base_value)
            key = partition_key.encode("utf-8")

            await asyncio.wait_for(
                producer.send_and_wait(topic, value=envelope, key=key),
                timeout=KAFKA_PUBLISH_TIMEOUT_SECONDS,
            )
            return True

        except TimeoutError:
            logger.warning(
                f"Timeout publishing event (topic={topic_base_value}, "
                f"timeout={KAFKA_PUBLISH_TIMEOUT_SECONDS}s)"
            )
            return False
        except Exception as e:
            logger.warning(f"Failed to publish event: {e}")
            return False
