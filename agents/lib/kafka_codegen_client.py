#!/usr/bin/env python3
"""
Kafka Client for Codegen Events

Lightweight wrapper around aiokafka for publishing/subscribing codegen events.
Follows resilience patterns similar to omninode_bridge Kafka client.

Framework Enhancements:
- Event optimizer integration for batch processing
- Circuit breaker for failure resilience
- Connection pooling for better performance
- Performance target: p95 latency ≤200ms
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator, Dict, List, Optional

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from .codegen_events import BaseEvent
from .version_config import get_config


# Optional confluent fallback
try:
    from .kafka_confluent_client import ConfluentKafkaClient  # type: ignore
except Exception:  # pragma: no cover
    ConfluentKafkaClient = None  # type: ignore

# Optional event optimizer
try:
    from .event_optimizer import EventOptimizer, OptimizerConfig  # type: ignore
except Exception:  # pragma: no cover
    EventOptimizer = None  # type: ignore
    OptimizerConfig = None  # type: ignore


class KafkaCodegenClient:
    def __init__(
        self,
        bootstrap_servers: Optional[str] = None,
        group_id: Optional[str] = None,
        host_rewrite: Optional[Dict[str, str]] = None,
        enable_optimizer: bool = True,
        optimizer_config: Optional[OptimizerConfig] = None,
    ) -> None:
        cfg = get_config()
        self.bootstrap_servers = bootstrap_servers or cfg.kafka_bootstrap_servers
        self.group_id = group_id or "omniclaude-codegen-consumer"
        # Host rewrite for development environments (disabled by default - use remote broker)
        # Only enable if explicitly provided via host_rewrite parameter
        self.host_rewrite = host_rewrite or {}
        self._producer: Optional[AIOKafkaProducer] = None
        self._consumer: Optional[AIOKafkaConsumer] = None

        # Framework: Event optimizer integration
        self._optimizer: Optional[EventOptimizer] = None
        self._enable_optimizer = enable_optimizer and EventOptimizer is not None
        self._optimizer_config = optimizer_config

        self.logger = logging.getLogger(__name__)

    def _rewrite_bootstrap(self, servers: str) -> str:
        if not self.host_rewrite:
            return servers
        out = servers
        for src, dst in self.host_rewrite.items():
            out = out.replace(src, dst)
        return out

    async def start_producer(self) -> None:
        if self._producer is None:
            bs = self._rewrite_bootstrap(self.bootstrap_servers)
            self._producer = AIOKafkaProducer(
                bootstrap_servers=bs,
                compression_type="gzip",
                linger_ms=20,
                acks="all",
                api_version="auto",  # Auto-detect broker API version
                request_timeout_ms=30000,  # Increase timeout to 30s
            )
            await self._producer.start()

    async def stop_producer(self) -> None:
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None

        # Cleanup optimizer
        if self._optimizer is not None:
            await self._optimizer.cleanup()
            self._optimizer = None

    async def start_consumer(self, topic: str) -> None:
        if self._consumer is None:
            bs = self._rewrite_bootstrap(self.bootstrap_servers)
            self._consumer = AIOKafkaConsumer(
                topic,
                bootstrap_servers=bs,
                group_id=self.group_id,
                enable_auto_commit=True,
                auto_offset_reset="latest",
            )
            await self._consumer.start()

    async def stop_consumer(self) -> None:
        if self._consumer is not None:
            await self._consumer.stop()
            self._consumer = None

    async def _ensure_optimizer(self) -> EventOptimizer:
        """Ensure event optimizer is initialized"""
        if self._optimizer is None:
            bs = self._rewrite_bootstrap(self.bootstrap_servers)
            self._optimizer = EventOptimizer(
                bootstrap_servers=bs, config=self._optimizer_config
            )
        return self._optimizer

    async def publish(self, event: BaseEvent) -> None:
        """
        Publish single event.

        Framework: Uses event optimizer if enabled for better performance.
        Falls back to direct publishing if optimizer unavailable.
        """
        # Try optimizer first if enabled
        if self._enable_optimizer:
            try:
                optimizer = await self._ensure_optimizer()
                await optimizer.publish_event(event)
                return
            except Exception as e:
                self.logger.warning(
                    f"Optimizer publish failed, falling back to direct: {e}"
                )

        # Fallback to direct publishing
        try:
            await self.start_producer()
            if self._producer is None:
                raise RuntimeError("Failed to start Kafka producer - producer is None")
            topic = event.to_kafka_topic()
            payload = json.dumps(
                {
                    "id": str(event.id),
                    "service": event.service,
                    "timestamp": event.timestamp,
                    "correlation_id": str(event.correlation_id),
                    "metadata": event.metadata,
                    "payload": event.payload,
                }
            ).encode("utf-8")
            await self._producer.send_and_wait(topic, payload)
        except Exception as e:
            # Fallback to confluent client if available
            self.logger.warning(
                f"aiokafka publish failed, attempting confluent fallback: {e}"
            )
            if ConfluentKafkaClient is None:
                raise
            client = ConfluentKafkaClient(
                self._rewrite_bootstrap(self.bootstrap_servers)
            )
            client.publish(
                event.to_kafka_topic(),
                {
                    "id": str(event.id),
                    "service": event.service,
                    "timestamp": event.timestamp,
                    "correlation_id": str(event.correlation_id),
                    "metadata": event.metadata,
                    "payload": event.payload,
                },
            )

    async def publish_batch(self, events: List[BaseEvent]) -> None:
        """
        Publish batch of events efficiently.

        Framework: Uses event optimizer for optimized batch processing.
        Performance target: p95 latency ≤200ms

        Args:
            events: List of events to publish
        """
        if not events:
            return

        # Try optimizer first if enabled
        if self._enable_optimizer:
            try:
                optimizer = await self._ensure_optimizer()
                await optimizer.publish_batch(events)
                return
            except Exception as e:
                self.logger.warning(
                    f"Batch publish via optimizer failed, falling back: {e}"
                )

        # Fallback: publish individually
        for event in events:
            await self.publish(event)

    async def consume(self, topic: str) -> AsyncIterator[dict]:
        try:
            await self.start_consumer(topic)
            if self._consumer is None:
                raise RuntimeError("Failed to start Kafka consumer - consumer is None")
            async for msg in self._consumer:
                try:
                    yield json.loads(msg.value.decode("utf-8"))
                except Exception as e:  # noqa: S112
                    # Skip malformed messages
                    self.logger.debug(f"Skipping malformed message: {e}")
                    continue
        except Exception as e:
            self.logger.warning(
                f"aiokafka consume failed, attempting confluent fallback: {e}"
            )
            if ConfluentKafkaClient is None:
                raise
            # Confluent client does not support async iteration; yield one and return
            client = ConfluentKafkaClient(
                self._rewrite_bootstrap(self.bootstrap_servers), self.group_id
            )
            payload = client.consume_one(topic, timeout_sec=10.0)
            if payload is not None:
                yield payload

    async def consume_until(
        self, topic: str, predicate, timeout_seconds: float = 30.0
    ) -> Optional[dict]:
        """Consume messages until predicate(payload) is True or timeout expires."""
        try:
            await self.start_consumer(topic)
            if self._consumer is None:
                raise RuntimeError("Failed to start Kafka consumer - consumer is None")

            async def _wait():
                async for msg in self._consumer:
                    try:
                        payload = json.loads(msg.value.decode("utf-8"))
                    except Exception as e:  # noqa: S112
                        self.logger.debug(f"Skipping malformed message: {e}")
                        continue
                    if predicate(payload):
                        return payload
                return None

            return await asyncio.wait_for(_wait(), timeout=timeout_seconds)
        except Exception as e:
            self.logger.warning(
                f"aiokafka consume_until failed, attempting confluent fallback: {e}"
            )
            if ConfluentKafkaClient is None:
                raise
            client = ConfluentKafkaClient(
                self._rewrite_bootstrap(self.bootstrap_servers), self.group_id
            )
            # Poll in small intervals until timeout
            end = asyncio.get_event_loop().time() + timeout_seconds
            while asyncio.get_event_loop().time() < end:
                payload = client.consume_one(topic, timeout_sec=1.0)
                if payload and predicate(payload):
                    return payload
            return None
