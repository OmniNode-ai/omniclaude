#!/usr/bin/env python3
"""
Kafka Client for Codegen Events

Lightweight wrapper around aiokafka for publishing/subscribing codegen events.
Follows resilience patterns similar to omninode_bridge Kafka client.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator, Callable, Optional, Dict

from aiokafka import AIOKafkaProducer, AIOKafkaConsumer

from .codegen_events import BaseEvent
from .version_config import get_config

# Optional confluent fallback
try:
    from .kafka_confluent_client import ConfluentKafkaClient  # type: ignore
except Exception:  # pragma: no cover
    ConfluentKafkaClient = None  # type: ignore


class KafkaCodegenClient:
    def __init__(
        self,
        bootstrap_servers: Optional[str] = None,
        group_id: Optional[str] = None,
        host_rewrite: Optional[Dict[str, str]] = None,
    ) -> None:
        cfg = get_config()
        self.bootstrap_servers = bootstrap_servers or cfg.kafka_bootstrap_servers
        self.group_id = group_id or "omniclaude-codegen-consumer"
        # Default host rewrite to smooth local Redpanda dev: container host -> localhost mapped port
        default_rewrite = {
            "omninode-bridge-redpanda:9092": "localhost:29092",            
        }
        self.host_rewrite = {**default_rewrite, **(host_rewrite or {})}
        self._producer: Optional[AIOKafkaProducer] = None
        self._consumer: Optional[AIOKafkaConsumer] = None
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
            )
            await self._producer.start()

    async def stop_producer(self) -> None:
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None

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

    async def publish(self, event: BaseEvent) -> None:
        try:
            await self.start_producer()
            assert self._producer is not None
            topic = event.to_kafka_topic()
            payload = json.dumps({
                "id": str(event.id),
                "service": event.service,
                "timestamp": event.timestamp,
                "correlation_id": str(event.correlation_id),
                "metadata": event.metadata,
                "payload": event.payload,
            }).encode("utf-8")
            await self._producer.send_and_wait(topic, payload)
        except Exception as e:
            # Fallback to confluent client if available
            self.logger.warning(f"aiokafka publish failed, attempting confluent fallback: {e}")
            if ConfluentKafkaClient is None:
                raise
            client = ConfluentKafkaClient(self._rewrite_bootstrap(self.bootstrap_servers))
            client.publish(event.to_kafka_topic(), {
                "id": str(event.id),
                "service": event.service,
                "timestamp": event.timestamp,
                "correlation_id": str(event.correlation_id),
                "metadata": event.metadata,
                "payload": event.payload,
            })

    async def consume(self, topic: str) -> AsyncIterator[dict]:
        try:
            await self.start_consumer(topic)
            assert self._consumer is not None
            async for msg in self._consumer:
                try:
                    yield json.loads(msg.value.decode("utf-8"))
                except Exception:
                    # Skip malformed messages
                    continue
        except Exception as e:
            self.logger.warning(f"aiokafka consume failed, attempting confluent fallback: {e}")
            if ConfluentKafkaClient is None:
                raise
            # Confluent client does not support async iteration; yield one and return
            client = ConfluentKafkaClient(self._rewrite_bootstrap(self.bootstrap_servers), self.group_id)
            payload = client.consume_one(topic, timeout_sec=10.0)
            if payload is not None:
                yield payload

    async def consume_until(self, topic: str, predicate, timeout_seconds: float = 30.0) -> Optional[dict]:
        """Consume messages until predicate(payload) is True or timeout expires."""
        try:
            await self.start_consumer(topic)
            assert self._consumer is not None
            async def _wait():
                async for msg in self._consumer:
                    try:
                        payload = json.loads(msg.value.decode("utf-8"))
                    except Exception:
                        continue
                    if predicate(payload):
                        return payload
                return None
            return await asyncio.wait_for(_wait(), timeout=timeout_seconds)
        except Exception as e:
            self.logger.warning(f"aiokafka consume_until failed, attempting confluent fallback: {e}")
            if ConfluentKafkaClient is None:
                raise
            client = ConfluentKafkaClient(self._rewrite_bootstrap(self.bootstrap_servers), self.group_id)
            # Poll in small intervals until timeout
            end = asyncio.get_event_loop().time() + timeout_seconds
            while asyncio.get_event_loop().time() < end:
                payload = client.consume_one(topic, timeout_sec=1.0)
                if payload and predicate(payload):
                    return payload
            return None


