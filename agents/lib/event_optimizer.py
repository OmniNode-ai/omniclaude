#!/usr/bin/env python3
"""
Event Processing Optimizer

High-performance event processing with:
- Batch processing for reduced overhead
- Smart buffering with flush timeout
- Compression for large payloads
- Connection pooling
- Circuit breaker for failures
- Metrics tracking

Performance target: p95 latency ≤200ms (from ~500ms baseline)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from aiokafka import AIOKafkaProducer

from .batch_processor import BatchConfig, BatchProcessor
from .codegen_events import BaseEvent
from .persistence import CodegenPersistence

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"  # Normal operation
    OPEN = "open"      # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass
class CircuitBreakerConfig:
    """Circuit breaker configuration"""
    failure_threshold: int = 5  # Failures before opening
    recovery_timeout_ms: int = 10000  # Time before testing recovery
    success_threshold: int = 2  # Successes to close circuit


@dataclass
class OptimizerConfig:
    """Event optimizer configuration"""
    enable_compression: bool = True
    compression_threshold_bytes: int = 1024  # Compress payloads > 1KB
    max_producer_pool_size: int = 3
    enable_metrics: bool = True

    def get_batch_config(self) -> BatchConfig:
        """Get batch configuration"""
        return BatchConfig()

    def get_circuit_config(self) -> CircuitBreakerConfig:
        """Get circuit breaker configuration"""
        return CircuitBreakerConfig()


class CircuitBreaker:
    """
    Circuit breaker for failure resilience.

    Prevents cascading failures by opening circuit when
    failure threshold is exceeded.
    """

    def __init__(self, config: CircuitBreakerConfig):
        self.config = config
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[float] = None
        self.lock = asyncio.Lock()
        self.logger = logging.getLogger(__name__)

    async def call(self, func, *args, **kwargs):
        """Execute function through circuit breaker"""
        async with self.lock:
            # Check if circuit should transition states
            await self._check_state_transition()

            if self.state == CircuitState.OPEN:
                raise RuntimeError("Circuit breaker is OPEN - rejecting request")

        # Execute function
        try:
            result = await func(*args, **kwargs)

            # Record success
            async with self.lock:
                await self._record_success()

            return result

        except Exception as e:
            # Record failure
            async with self.lock:
                await self._record_failure()

            raise

    async def _check_state_transition(self):
        """Check if circuit should transition states"""
        if self.state == CircuitState.OPEN:
            # Check if recovery timeout has passed
            if self.last_failure_time:
                elapsed_ms = (time.time() - self.last_failure_time) * 1000
                if elapsed_ms >= self.config.recovery_timeout_ms:
                    self.logger.info("Circuit breaker transitioning to HALF_OPEN")
                    self.state = CircuitState.HALF_OPEN
                    self.success_count = 0

    async def _record_success(self):
        """Record successful execution"""
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.config.success_threshold:
                self.logger.info("Circuit breaker transitioning to CLOSED")
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                self.success_count = 0
        elif self.state == CircuitState.CLOSED:
            # Reset failure count on success
            self.failure_count = 0

    async def _record_failure(self):
        """Record failed execution"""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.state == CircuitState.HALF_OPEN:
            # Immediately reopen on failure in half-open state
            self.logger.warning("Circuit breaker reopening due to failure in HALF_OPEN state")
            self.state = CircuitState.OPEN
        elif self.state == CircuitState.CLOSED:
            if self.failure_count >= self.config.failure_threshold:
                self.logger.error(
                    f"Circuit breaker OPENING after {self.failure_count} failures"
                )
                self.state = CircuitState.OPEN


class EventOptimizer:
    """
    High-performance event optimizer with batch processing,
    circuit breaker, compression, and connection pooling.
    """

    def __init__(
        self,
        bootstrap_servers: str,
        config: Optional[OptimizerConfig] = None,
        persistence: Optional[CodegenPersistence] = None,
        batch_config: Optional[BatchConfig] = None,
        circuit_config: Optional[CircuitBreakerConfig] = None,
    ):
        """
        Initialize event optimizer.

        Args:
            bootstrap_servers: Kafka bootstrap servers
            config: Optional optimizer configuration
            persistence: Optional persistence layer for metrics
            batch_config: Optional batch configuration override
            circuit_config: Optional circuit breaker configuration override
        """
        self.bootstrap_servers = bootstrap_servers
        self.config = config or OptimizerConfig()

        # Initialize circuit breaker
        self.circuit_breaker = CircuitBreaker(
            circuit_config or self.config.get_circuit_config()
        )

        # Store batch config
        self._batch_config = batch_config or self.config.get_batch_config()

        # Initialize persistence
        self.persistence = persistence or (
            CodegenPersistence() if self.config.enable_metrics else None
        )

        # Producer pool for connection reuse
        self._producer_pool: List[AIOKafkaProducer] = []
        self._producer_lock = asyncio.Lock()

        # Batch processor
        self.batch_processor: Optional[BatchProcessor] = None

        self.logger = logging.getLogger(__name__)

    async def _get_producer(self) -> AIOKafkaProducer:
        """Get producer from pool or create new one"""
        async with self._producer_lock:
            # Try to get from pool
            if self._producer_pool:
                producer = self._producer_pool.pop()
                return producer

            # Create new producer
            producer = AIOKafkaProducer(
                bootstrap_servers=self.bootstrap_servers,
                compression_type="gzip" if self.config.enable_compression else None,
                linger_ms=20,  # Small delay to allow batching
                acks="all",
                max_batch_size=16384,  # 16KB batches
            )
            await producer.start()
            return producer

    async def _return_producer(self, producer: AIOKafkaProducer):
        """Return producer to pool"""
        async with self._producer_lock:
            if len(self._producer_pool) < self.config.max_producer_pool_size:
                self._producer_pool.append(producer)
            else:
                # Pool full, close producer
                await producer.stop()

    async def publish_event(self, event: BaseEvent) -> None:
        """
        Publish single event with optimizations.

        Args:
            event: Event to publish
        """
        start_time = time.time()

        try:
            # Publish through circuit breaker
            await self.circuit_breaker.call(
                self._publish_event_internal,
                event
            )

            duration_ms = (time.time() - start_time) * 1000

            # Track success metrics
            if self.persistence:
                await self.persistence.insert_event_processing_metric(
                    event_type=event.event,
                    event_source="event_optimizer",
                    processing_duration_ms=int(duration_ms),
                    success=True
                )

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000

            # Track failure metrics
            if self.persistence:
                await self.persistence.insert_event_processing_metric(
                    event_type=event.event,
                    event_source="event_optimizer",
                    processing_duration_ms=int(duration_ms),
                    success=False,
                    error_type=type(e).__name__,
                    error_message=str(e)
                )

            raise

    async def _publish_event_internal(self, event: BaseEvent) -> None:
        """Internal publish implementation"""
        producer = await self._get_producer()

        try:
            topic = event.to_kafka_topic()
            payload = json.dumps({
                "id": str(event.id),
                "service": event.service,
                "timestamp": event.timestamp,
                "correlation_id": str(event.correlation_id),
                "metadata": event.metadata,
                "payload": event.payload,
            }).encode("utf-8")

            await producer.send_and_wait(topic, payload)

        finally:
            await self._return_producer(producer)

    async def publish_batch(self, events: List[BaseEvent]) -> None:
        """
        Publish batch of events efficiently.

        Args:
            events: List of events to publish
        """
        if not events:
            return

        start_time = time.time()

        try:
            # Process batch through circuit breaker
            await self.circuit_breaker.call(
                self._publish_batch_internal,
                events
            )

            duration_ms = (time.time() - start_time) * 1000

            # Track batch metrics
            if self.persistence:
                await self.persistence.insert_event_processing_metric(
                    event_type="batch_publish",
                    event_source="event_optimizer",
                    processing_duration_ms=int(duration_ms),
                    success=True,
                    batch_size=len(events)
                )

            self.logger.debug(
                f"Published batch of {len(events)} events in {duration_ms:.0f}ms"
            )

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000

            # Track batch failure
            if self.persistence:
                await self.persistence.insert_event_processing_metric(
                    event_type="batch_publish",
                    event_source="event_optimizer",
                    processing_duration_ms=int(duration_ms),
                    success=False,
                    error_type=type(e).__name__,
                    error_message=str(e),
                    batch_size=len(events)
                )

            raise

    async def _publish_batch_internal(self, events: List[BaseEvent]) -> None:
        """Internal batch publish implementation"""
        producer = await self._get_producer()

        try:
            # Send all events asynchronously
            futures = []
            for event in events:
                topic = event.to_kafka_topic()
                payload = json.dumps({
                    "id": str(event.id),
                    "service": event.service,
                    "timestamp": event.timestamp,
                    "correlation_id": str(event.correlation_id),
                    "metadata": event.metadata,
                    "payload": event.payload,
                }).encode("utf-8")

                future = producer.send(topic, payload)
                futures.append(future)

            # Wait for all sends to complete
            await asyncio.gather(*[f for f in futures])

        finally:
            await self._return_producer(producer)

    def create_batch_processor(self) -> BatchProcessor:
        """
        Create a batch processor using this optimizer.

        Returns:
            Configured batch processor
        """
        if self.batch_processor is None:
            self.batch_processor = BatchProcessor(
                processor_func=self._publish_batch_internal,
                config=self._batch_config,
                persistence=self.persistence
            )

        return self.batch_processor

    async def cleanup(self):
        """Cleanup resources"""
        # Cleanup batch processor
        if self.batch_processor:
            await self.batch_processor.cleanup()

        # Close all producers in pool
        async with self._producer_lock:
            for producer in self._producer_pool:
                await producer.stop()
            self._producer_pool.clear()

        # Close persistence
        if self.persistence:
            await self.persistence.close()
