# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Kafka consumer for Claude Code session events.

Implements at-least-once delivery with manual offset commits.
Events are processed through a ProtocolSessionAggregator.

This consumer subscribes to Claude Code hook event topics and processes
incoming events through the session aggregation system. It implements
several resilience patterns:

    - At-least-once delivery: Manual offset commits after successful processing
    - Circuit breaker: Prevents cascade failures when downstream is unhealthy
    - Graceful shutdown: Properly drains and commits before exiting
    - Observability: Structured logging with correlation IDs

Architecture:
    ```
    Kafka Topics (session/prompt/tool)
           |
           v
    SessionEventConsumer
           |
           v (process_event)
    ProtocolSessionAggregator
           |
           v
    Session Snapshots (storage)
    ```

Related Tickets:
    - OMN-1401: Session storage in OmniMemory (current)
    - OMN-1400: Hook handlers emit to Kafka
    - OMN-1402: Learning compute node (consumer of snapshots)

Example:
    >>> from omniclaude.consumers import SessionEventConsumer, ConfigSessionConsumer
    >>> from my_aggregator import MySessionAggregator
    >>>
    >>> config = ConfigSessionConsumer()
    >>> aggregator = MySessionAggregator()
    >>> consumer = SessionEventConsumer(config=config, aggregator=aggregator)
    >>>
    >>> # Start consuming (blocking)
    >>> await consumer.start()
    >>>
    >>> # Or use context manager
    >>> async with consumer:
    ...     await consumer.run()
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from aiokafka import AIOKafkaConsumer
from aiokafka.errors import KafkaError
from pydantic import ValidationError

from omniclaude.consumers.config import ConfigSessionConsumer
from omniclaude.hooks.schemas import (
    HookEventType,
    ModelHookEventEnvelope,
    ModelHookPromptSubmittedPayload,
    ModelHookSessionEndedPayload,
    ModelHookSessionStartedPayload,
    ModelHookToolExecutedPayload,
)

if TYPE_CHECKING:
    from omniclaude.aggregators.protocol_session_aggregator import (
        ProtocolSessionAggregator,
    )

logger = logging.getLogger(__name__)


# =============================================================================
# Enums
# =============================================================================


class EnumCircuitState(StrEnum):
    """Circuit breaker states.

    The circuit breaker protects the consumer from cascade failures when
    the downstream aggregator is unhealthy.

    State Transitions:
        CLOSED -> OPEN: After consecutive_failures >= threshold
        OPEN -> HALF_OPEN: After circuit_breaker_timeout_seconds elapsed
        HALF_OPEN -> CLOSED: After successful processing
        HALF_OPEN -> OPEN: After failure in half-open state
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


# =============================================================================
# Consumer Metrics
# =============================================================================


class ConsumerMetrics:
    """Metrics tracking for the session event consumer.

    Tracks processing statistics for observability and monitoring.
    Thread-safe via asyncio lock protection.

    Attributes:
        messages_received: Total messages received from Kafka.
        messages_processed: Successfully processed messages.
        messages_failed: Messages that failed processing.
        messages_skipped: Messages skipped (invalid, duplicate, etc.).
        circuit_opens: Number of times circuit breaker opened.
        last_message_at: Timestamp of last received message.
    """

    def __init__(self) -> None:
        """Initialize metrics with zero values."""
        self.messages_received: int = 0
        self.messages_processed: int = 0
        self.messages_failed: int = 0
        self.messages_skipped: int = 0
        self.circuit_opens: int = 0
        self.last_message_at: datetime | None = None
        self._lock = asyncio.Lock()

    async def record_received(self) -> None:
        """Record a message received."""
        async with self._lock:
            self.messages_received += 1
            self.last_message_at = datetime.now(UTC)

    async def record_processed(self) -> None:
        """Record a successfully processed message."""
        async with self._lock:
            self.messages_processed += 1

    async def record_failed(self) -> None:
        """Record a failed message."""
        async with self._lock:
            self.messages_failed += 1

    async def record_skipped(self) -> None:
        """Record a skipped message."""
        async with self._lock:
            self.messages_skipped += 1

    async def record_circuit_open(self) -> None:
        """Record a circuit breaker open event."""
        async with self._lock:
            self.circuit_opens += 1

    async def snapshot(self) -> dict[str, object]:
        """Get a snapshot of current metrics.

        Returns:
            Dictionary with all metric values.
        """
        async with self._lock:
            return {
                "messages_received": self.messages_received,
                "messages_processed": self.messages_processed,
                "messages_failed": self.messages_failed,
                "messages_skipped": self.messages_skipped,
                "circuit_opens": self.circuit_opens,
                "last_message_at": (
                    self.last_message_at.isoformat() if self.last_message_at else None
                ),
            }


# =============================================================================
# Session Event Consumer
# =============================================================================


class SessionEventConsumer:
    """Kafka consumer for Claude Code hook events.

    Consumes events from session/prompt/tool topics and processes
    them through an aggregator. Implements at-least-once delivery
    with manual offset commits.

    Features:
        - **At-least-once delivery**: Offsets committed only after successful
          processing. If the consumer crashes before commit, messages will be
          reprocessed on restart (aggregator must be idempotent).

        - **Circuit breaker**: Protects against cascade failures when the
          downstream aggregator is unhealthy. Opens after consecutive failures
          exceed threshold, allowing time for recovery.

        - **Graceful shutdown**: Drains in-flight messages and commits offsets
          before exiting. Responds to stop() or SIGTERM signals.

        - **Observability**: Structured logging with correlation IDs, plus
          metrics tracking for monitoring dashboards.

    Thread Safety:
        This consumer is designed for single-threaded async execution.
        Multiple consumers can run in parallel with different group_ids
        for horizontal scaling.

    Example:
        >>> config = ConfigSessionConsumer()
        >>> aggregator = InMemorySessionAggregator()
        >>> consumer = SessionEventConsumer(config=config, aggregator=aggregator)
        >>>
        >>> # Start consuming
        >>> await consumer.start()
        >>>
        >>> # Or in application lifecycle
        >>> await consumer.start()
        >>> try:
        ...     await consumer.run()
        ... finally:
        ...     await consumer.stop()

    Attributes:
        metrics: Consumer metrics for observability.
        is_running: Whether the consumer is currently running.
        circuit_state: Current circuit breaker state.
    """

    def __init__(
        self,
        config: ConfigSessionConsumer,
        aggregator: ProtocolSessionAggregator[object, object],
    ) -> None:
        """Initialize the session event consumer.

        Args:
            config: Consumer configuration (topics, timeouts, circuit breaker).
            aggregator: Session aggregator implementing ProtocolSessionAggregator.
                The aggregator must be idempotent to support at-least-once delivery.

        Example:
            >>> config = ConfigSessionConsumer(
            ...     bootstrap_servers="192.168.86.200:29092",
            ...     group_id="my-consumer-group",
            ... )
            >>> aggregator = InMemorySessionAggregator()
            >>> consumer = SessionEventConsumer(config, aggregator)
        """
        self._config = config
        self._aggregator = aggregator
        self._consumer: AIOKafkaConsumer | None = None
        self._running = False
        self._shutdown_event = asyncio.Event()

        # Circuit breaker state
        self._consecutive_failures = 0
        self._circuit_state = EnumCircuitState.CLOSED
        self._circuit_opened_at: datetime | None = None
        self._circuit_lock = asyncio.Lock()
        self._consumer_paused = False  # Track pause state for circuit breaker

        # Metrics
        self.metrics = ConsumerMetrics()

        # Consumer ID for logging
        self._consumer_id = f"session-consumer-{uuid4().hex[:8]}"

        logger.info(
            "SessionEventConsumer initialized",
            extra={
                "consumer_id": self._consumer_id,
                "topics": self._config.topics,
                "group_id": self._config.group_id,
                "bootstrap_servers": self._config.bootstrap_servers,
            },
        )

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def is_running(self) -> bool:
        """Check if the consumer is currently running.

        Returns:
            True if start() has been called and stop() has not.
        """
        return self._running

    @property
    def circuit_state(self) -> EnumCircuitState:
        """Get the current circuit breaker state.

        Returns:
            Current circuit state (CLOSED, OPEN, or HALF_OPEN).
        """
        return self._circuit_state

    @property
    def consumer_id(self) -> str:
        """Get the unique consumer identifier.

        Returns:
            Consumer ID string for logging and tracing.
        """
        return self._consumer_id

    # =========================================================================
    # Lifecycle Methods
    # =========================================================================

    async def start(self) -> None:
        """Start the consumer and connect to Kafka.

        Creates the Kafka consumer with manual offset commits disabled
        (for at-least-once semantics) and starts the connection.

        Raises:
            RuntimeError: If the consumer is already running.
            KafkaError: If connection to Kafka fails.

        Example:
            >>> await consumer.start()
            >>> # Consumer is now connected, ready for run()
        """
        if self._running:
            logger.warning(
                "Consumer already running",
                extra={"consumer_id": self._consumer_id},
            )
            return

        correlation_id = uuid4()

        logger.info(
            "Starting SessionEventConsumer",
            extra={
                "consumer_id": self._consumer_id,
                "correlation_id": str(correlation_id),
                "topics": self._config.topics,
            },
        )

        try:
            self._consumer = AIOKafkaConsumer(
                *self._config.topics,
                bootstrap_servers=self._config.bootstrap_servers,
                group_id=self._config.group_id,
                auto_offset_reset=self._config.auto_offset_reset,
                enable_auto_commit=False,  # Manual commits for at-least-once
                max_poll_records=self._config.max_poll_records,
            )

            await self._consumer.start()
            self._running = True
            self._shutdown_event.clear()

            logger.info(
                "SessionEventConsumer started",
                extra={
                    "consumer_id": self._consumer_id,
                    "correlation_id": str(correlation_id),
                    "topics": self._config.topics,
                    "group_id": self._config.group_id,
                },
            )

        except KafkaError as e:
            logger.exception(
                "Failed to start consumer",
                extra={
                    "consumer_id": self._consumer_id,
                    "correlation_id": str(correlation_id),
                    "error": str(e),
                },
            )
            raise

    async def stop(self) -> None:
        """Stop the consumer gracefully.

        Signals the consume loop to exit, waits for in-flight processing
        to complete, and closes the Kafka consumer connection. Safe to
        call multiple times.

        Example:
            >>> await consumer.stop()
            >>> # Consumer is now stopped and disconnected
        """
        if not self._running:
            logger.debug(
                "Consumer not running, nothing to stop",
                extra={"consumer_id": self._consumer_id},
            )
            return

        correlation_id = uuid4()

        logger.info(
            "Stopping SessionEventConsumer",
            extra={
                "consumer_id": self._consumer_id,
                "correlation_id": str(correlation_id),
            },
        )

        # Signal shutdown
        self._running = False
        self._shutdown_event.set()

        # Resume consumer if paused (cleanup before stop)
        if self._consumer is not None and self._consumer_paused:
            await self._resume_consumer(correlation_id)

        # Close consumer connection
        if self._consumer is not None:
            try:
                await self._consumer.stop()
            except Exception as e:
                logger.warning(
                    "Error stopping Kafka consumer",
                    extra={
                        "consumer_id": self._consumer_id,
                        "correlation_id": str(correlation_id),
                        "error": str(e),
                    },
                )
            finally:
                self._consumer = None

        # Log final metrics
        metrics_snapshot = await self.metrics.snapshot()
        logger.info(
            "SessionEventConsumer stopped",
            extra={
                "consumer_id": self._consumer_id,
                "correlation_id": str(correlation_id),
                "final_metrics": metrics_snapshot,
            },
        )

    async def run(self) -> None:
        """Run the main consume loop.

        Continuously consumes messages from Kafka topics and processes them
        through the aggregator. Implements at-least-once delivery by committing
        offsets only after successful processing.

        This method blocks until stop() is called or an unrecoverable error
        occurs. Use this after calling start().

        Example:
            >>> await consumer.start()
            >>> try:
            ...     await consumer.run()
            ... finally:
            ...     await consumer.stop()
        """
        if not self._running or self._consumer is None:
            raise RuntimeError(
                "Consumer not started. Call start() before run().",
            )

        correlation_id = uuid4()

        logger.info(
            "Starting consume loop",
            extra={
                "consumer_id": self._consumer_id,
                "correlation_id": str(correlation_id),
            },
        )

        await self._consume_loop(correlation_id)

    async def __aenter__(self) -> SessionEventConsumer:
        """Async context manager entry.

        Starts the consumer and returns self for use in async with blocks.

        Returns:
            Self for chaining.

        Example:
            >>> async with SessionEventConsumer(config, aggregator) as consumer:
            ...     await consumer.run()
        """
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Async context manager exit.

        Stops the consumer on exit from async with block.
        """
        await self.stop()

    # =========================================================================
    # Consume Loop
    # =========================================================================

    async def _consume_loop(self, correlation_id: UUID) -> None:
        """Main consumption loop with at-least-once semantics.

        Continuously polls Kafka for messages and processes them through
        the aggregator. Commits offsets only after successful processing.

        Args:
            correlation_id: Correlation ID for tracing this consume session.
        """
        if self._consumer is None:
            logger.error(
                "Consumer is None in consume loop",
                extra={
                    "consumer_id": self._consumer_id,
                    "correlation_id": str(correlation_id),
                },
            )
            return

        try:
            async for message in self._consumer:
                # Check shutdown signal
                if not self._running:
                    logger.debug(
                        "Shutdown signal received, exiting consume loop",
                        extra={
                            "consumer_id": self._consumer_id,
                            "correlation_id": str(correlation_id),
                        },
                    )
                    break

                # Record message received
                await self.metrics.record_received()

                # Check circuit breaker - if open, pause and wait for recovery
                # IMPORTANT: We do NOT skip this message. After circuit recovers,
                # we process it normally. This prevents message loss during circuit open.
                if await self._is_circuit_open():
                    await self._wait_for_circuit_recovery(correlation_id)
                    # Fall through to process this message after recovery

                # Process the message
                message_correlation_id = uuid4()
                try:
                    success = await self._process_message(
                        message, message_correlation_id
                    )

                    if success:
                        # Commit offset after successful processing
                        await self._consumer.commit()
                        await self.metrics.record_processed()
                        await self._record_success()

                        logger.debug(
                            "Message processed and committed",
                            extra={
                                "consumer_id": self._consumer_id,
                                "correlation_id": str(message_correlation_id),
                                "topic": message.topic,
                                "partition": message.partition,
                                "offset": message.offset,
                            },
                        )
                    else:
                        # Processing returned False (rejected, duplicate, etc.)
                        # Still commit to avoid reprocessing
                        await self._consumer.commit()
                        await self.metrics.record_skipped()

                        logger.debug(
                            "Message skipped (rejected by aggregator)",
                            extra={
                                "consumer_id": self._consumer_id,
                                "correlation_id": str(message_correlation_id),
                                "topic": message.topic,
                            },
                        )

                except ValidationError as e:
                    # Schema validation error - skip and commit
                    # These messages are malformed and will never succeed
                    await self._consumer.commit()
                    await self.metrics.record_skipped()

                    logger.warning(
                        "Message skipped due to validation error",
                        extra={
                            "consumer_id": self._consumer_id,
                            "correlation_id": str(message_correlation_id),
                            "topic": message.topic,
                            "error": str(e),
                        },
                    )

                except Exception as e:
                    # Processing error - record failure, don't commit
                    await self.metrics.record_failed()
                    await self._record_failure()

                    logger.exception(
                        "Error processing message",
                        extra={
                            "consumer_id": self._consumer_id,
                            "correlation_id": str(message_correlation_id),
                            "topic": message.topic,
                            "partition": message.partition,
                            "offset": message.offset,
                            "error": str(e),
                            "consecutive_failures": self._consecutive_failures,
                        },
                    )

        except asyncio.CancelledError:
            logger.info(
                "Consume loop cancelled",
                extra={
                    "consumer_id": self._consumer_id,
                    "correlation_id": str(correlation_id),
                },
            )
            raise

        except Exception as e:
            logger.exception(
                "Unexpected error in consume loop",
                extra={
                    "consumer_id": self._consumer_id,
                    "correlation_id": str(correlation_id),
                    "error": str(e),
                },
            )
            raise

        finally:
            logger.info(
                "Consume loop exiting",
                extra={
                    "consumer_id": self._consumer_id,
                    "correlation_id": str(correlation_id),
                },
            )

    # =========================================================================
    # Message Processing
    # =========================================================================

    async def _process_message(self, message: object, correlation_id: UUID) -> bool:
        """Process a single message through the aggregator.

        Deserializes the message payload into a hook event envelope and
        dispatches it to the appropriate aggregator method.

        Args:
            message: Kafka ConsumerRecord with topic, value, etc.
            correlation_id: Correlation ID for this processing attempt.

        Returns:
            True if processed successfully, False if rejected (duplicate, etc.).

        Raises:
            ValidationError: If the message payload fails schema validation.
            Exception: If the aggregator raises an error during processing.
        """
        # Extract message value
        value = getattr(message, "value", None)
        if value is None:
            logger.warning(
                "Message has no value",
                extra={
                    "consumer_id": self._consumer_id,
                    "correlation_id": str(correlation_id),
                    "topic": getattr(message, "topic", "unknown"),
                },
            )
            return False

        # Decode bytes to string
        if isinstance(value, bytes):
            value = value.decode("utf-8")

        # Parse JSON into envelope
        envelope = ModelHookEventEnvelope.model_validate_json(value)

        # Extract payload for logging context only
        payload = envelope.payload

        logger.debug(
            "Processing event",
            extra={
                "consumer_id": self._consumer_id,
                "correlation_id": str(correlation_id),
                "event_type": envelope.event_type.value,
                "session_id": payload.session_id,
                "entity_id": str(payload.entity_id),
            },
        )

        # Process through aggregator
        # Pass full envelope - aggregator extracts payload and routes by event_type
        result = await self._aggregator.process_event(envelope, correlation_id)

        return result

    def _extract_session_id(self, payload: object) -> str | None:
        """Extract session_id from a payload object.

        Helper method to safely extract session_id regardless of payload type.

        Args:
            payload: One of the hook payload types.

        Returns:
            Session ID string, or None if not found.
        """
        if isinstance(
            payload,
            (
                ModelHookSessionStartedPayload,
                ModelHookSessionEndedPayload,
                ModelHookPromptSubmittedPayload,
                ModelHookToolExecutedPayload,
            ),
        ):
            return payload.session_id
        return None

    # =========================================================================
    # Circuit Breaker
    # =========================================================================

    async def _is_circuit_open(self) -> bool:
        """Check if circuit breaker is open.

        If the circuit is open, checks if enough time has passed to
        transition to half-open state for a test request.

        Returns:
            True if circuit is open and should block processing.
        """
        async with self._circuit_lock:
            if self._circuit_state == EnumCircuitState.CLOSED:
                return False

            if self._circuit_state == EnumCircuitState.HALF_OPEN:
                # Allow test request
                return False

            # Circuit is OPEN - check if timeout has elapsed
            if self._circuit_opened_at is not None:
                elapsed = (datetime.now(UTC) - self._circuit_opened_at).total_seconds()
                if elapsed >= self._config.circuit_breaker_timeout_seconds:
                    # Transition to half-open
                    self._circuit_state = EnumCircuitState.HALF_OPEN
                    logger.info(
                        "Circuit breaker transitioning to half-open",
                        extra={
                            "consumer_id": self._consumer_id,
                            "elapsed_seconds": elapsed,
                        },
                    )
                    return False

            return True

    async def _wait_for_circuit_recovery(self, correlation_id: UUID) -> None:
        """Pause consumer and wait for circuit breaker to recover.

        Called when the circuit is open. This method:
        1. Pauses the Kafka consumer to stop fetching new messages
        2. Waits in a loop until circuit transitions to HALF_OPEN or CLOSED
        3. Resumes the consumer before returning

        This ensures no messages are lost during circuit open state - the current
        message will be processed after this method returns, and no new messages
        are fetched while waiting.

        Args:
            correlation_id: Correlation ID for logging.
        """
        if self._consumer is None:
            return

        # Pause the consumer to stop fetching new messages
        await self._pause_consumer(correlation_id)

        logger.warning(
            "Circuit breaker is open, consumer paused - waiting for recovery",
            extra={
                "consumer_id": self._consumer_id,
                "correlation_id": str(correlation_id),
                "timeout_seconds": self._config.circuit_breaker_timeout_seconds,
            },
        )

        # Wait in a loop until circuit is no longer open
        check_interval = min(1.0, self._config.circuit_breaker_timeout_seconds / 10)
        while self._running:
            # Check if circuit has recovered
            if not await self._is_circuit_open():
                logger.info(
                    "Circuit breaker recovered, resuming consumer",
                    extra={
                        "consumer_id": self._consumer_id,
                        "correlation_id": str(correlation_id),
                        "circuit_state": self._circuit_state.value,
                    },
                )
                break

            # Check for shutdown signal
            if self._shutdown_event.is_set():
                logger.debug(
                    "Shutdown signal received while waiting for circuit recovery",
                    extra={
                        "consumer_id": self._consumer_id,
                        "correlation_id": str(correlation_id),
                    },
                )
                break

            # Wait before checking again
            await asyncio.sleep(check_interval)

        # Resume the consumer before returning
        await self._resume_consumer(correlation_id)

    async def _pause_consumer(self, correlation_id: UUID) -> None:
        """Pause the Kafka consumer on all assigned partitions.

        Args:
            correlation_id: Correlation ID for logging.
        """
        if self._consumer is None or self._consumer_paused:
            return

        try:
            partitions = self._consumer.assignment()
            if partitions:
                self._consumer.pause(*partitions)
                self._consumer_paused = True
                logger.debug(
                    "Consumer paused",
                    extra={
                        "consumer_id": self._consumer_id,
                        "correlation_id": str(correlation_id),
                        "partitions": [str(p) for p in partitions],
                    },
                )
        except Exception as e:
            logger.warning(
                "Failed to pause consumer",
                extra={
                    "consumer_id": self._consumer_id,
                    "correlation_id": str(correlation_id),
                    "error": str(e),
                },
            )

    async def _resume_consumer(self, correlation_id: UUID) -> None:
        """Resume the Kafka consumer on all assigned partitions.

        Args:
            correlation_id: Correlation ID for logging.
        """
        if self._consumer is None or not self._consumer_paused:
            return

        try:
            partitions = self._consumer.assignment()
            if partitions:
                self._consumer.resume(*partitions)
                self._consumer_paused = False
                logger.debug(
                    "Consumer resumed",
                    extra={
                        "consumer_id": self._consumer_id,
                        "correlation_id": str(correlation_id),
                        "partitions": [str(p) for p in partitions],
                    },
                )
        except Exception as e:
            logger.warning(
                "Failed to resume consumer",
                extra={
                    "consumer_id": self._consumer_id,
                    "correlation_id": str(correlation_id),
                    "error": str(e),
                },
            )

    async def _record_failure(self) -> None:
        """Record a processing failure for circuit breaker.

        Increments consecutive failure count and opens circuit if
        threshold is exceeded.
        """
        async with self._circuit_lock:
            self._consecutive_failures += 1

            if self._consecutive_failures >= self._config.circuit_breaker_threshold:
                if self._circuit_state != EnumCircuitState.OPEN:
                    self._circuit_state = EnumCircuitState.OPEN
                    self._circuit_opened_at = datetime.now(UTC)
                    await self.metrics.record_circuit_open()

                    logger.warning(
                        "Circuit breaker opened",
                        extra={
                            "consumer_id": self._consumer_id,
                            "consecutive_failures": self._consecutive_failures,
                            "threshold": self._config.circuit_breaker_threshold,
                        },
                    )

    async def _record_success(self) -> None:
        """Record a processing success for circuit breaker.

        Resets consecutive failure count and closes circuit if in
        half-open state. Also ensures consumer is resumed if it was paused.
        """
        should_resume = False
        async with self._circuit_lock:
            self._consecutive_failures = 0

            if self._circuit_state == EnumCircuitState.HALF_OPEN:
                self._circuit_state = EnumCircuitState.CLOSED
                self._circuit_opened_at = None
                should_resume = self._consumer_paused

                logger.info(
                    "Circuit breaker closed after successful request",
                    extra={
                        "consumer_id": self._consumer_id,
                    },
                )

        # Resume consumer outside the lock if needed (safety check)
        if should_resume:
            await self._resume_consumer(uuid4())

    # =========================================================================
    # Health Check
    # =========================================================================

    async def health_check(self) -> dict[str, object]:
        """Check consumer health status.

        Returns a dictionary with health information for monitoring
        and diagnostics.

        Returns:
            Dictionary with health status including:
                - healthy: Overall health (running and circuit closed)
                - running: Whether consume loop is active
                - circuit_state: Current circuit breaker state
                - consumer_id: Unique consumer identifier
                - metrics: Current metrics snapshot
        """
        metrics_snapshot = await self.metrics.snapshot()

        return {
            "healthy": self._running and self._circuit_state == EnumCircuitState.CLOSED,
            "running": self._running,
            "circuit_state": self._circuit_state.value,
            "consumer_paused": self._consumer_paused,
            "consumer_id": self._consumer_id,
            "group_id": self._config.group_id,
            "topics": self._config.topics,
            "consecutive_failures": self._consecutive_failures,
            "metrics": metrics_snapshot,
        }


__all__ = [
    "SessionEventConsumer",
    "ConsumerMetrics",
    "EnumCircuitState",
]
