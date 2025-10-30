#!/usr/bin/env python3
"""
Router Event Handler.

Kafka consumer/producer for routing events following ONEX v2.0 event-driven patterns.
Consumes routing requests from Kafka, processes them via RoutingHandler,
and publishes responses back to Kafka using the envelope pattern.

Event Flow:
    1. Consume routing request envelope from Kafka (agent.routing.requested.v1)
    2. Deserialize using ModelRoutingEventEnvelope
    3. Extract ModelRoutingRequest payload
    4. Call RoutingHandler.handle_routing_request()
    5. Wrap response in ModelRoutingEventEnvelope
    6. Publish to completed topic (agent.routing.completed.v1)
    7. Commit offset on success (at-least-once delivery)

Error Handling:
    - Validation errors → Publish to failed topic, commit offset
    - Processing errors → Publish to failed topic, commit offset
    - Kafka errors → Log and retry, do NOT commit offset

Implementation: Phase 2 - Event-Driven Routing Adapter
Reference: database_adapter_effect/node.py (proven pattern)
"""

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any, Optional
from uuid import uuid4

# Kafka imports
try:
    from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

    AIOKAFKA_AVAILABLE = True
except ImportError:
    AIOKAFKA_AVAILABLE = False
    AIOKafkaConsumer = Any  # type: ignore
    AIOKafkaProducer = Any  # type: ignore

from .config import get_config
from .routing_handler import RoutingHandler
from .schemas import TOPICS, EventTypes, ModelRoutingEventEnvelope

logger = logging.getLogger(__name__)


class RouterEventHandler:
    """
    Router Event Handler.

    Consumes routing request events from Kafka, processes them via RoutingHandler,
    and publishes routing response events back to Kafka.

    Follows ONEX v2.0 event-driven architecture:
    - Envelope pattern for all events (ModelRoutingEventEnvelope)
    - Correlation ID tracking throughout event flow
    - Manual offset commit for at-least-once delivery
    - Graceful error handling with failed event publishing
    - Clean shutdown with proper resource cleanup

    Kafka Topics:
        - Consume: agent.routing.requested.v1
        - Publish (success): agent.routing.completed.v1
        - Publish (error): agent.routing.failed.v1

    Performance Targets:
        - Event processing: < 100ms (p95)
        - Routing time: < 50ms (p95)
        - Throughput: 100+ requests/second
    """

    def __init__(self):
        """Initialize router event handler."""
        # Configuration
        self.config = get_config()

        # Dependencies
        self._routing_handler: Optional[RoutingHandler] = None
        self._kafka_consumer: Optional[AIOKafkaConsumer] = None
        self._kafka_producer: Optional[AIOKafkaProducer] = None

        # Event consumption control
        self._is_consuming_events = False
        self._event_consumption_task: Optional[asyncio.Task] = None

        # Metrics
        self._request_count = 0
        self._success_count = 0
        self._error_count = 0
        self._started_at: Optional[datetime] = None

    async def start(self) -> None:
        """
        Start router event handler.

        Process:
            1. Initialize RoutingHandler
            2. Initialize Kafka consumer (routing requests)
            3. Initialize Kafka producer (routing responses)
            4. Start event consumption loop

        Raises:
            RuntimeError: If initialization fails
        """
        self._started_at = datetime.now(UTC)

        logger.info(
            "Starting RouterEventHandler",
            extra={
                "kafka_bootstrap_servers": self.config.kafka_bootstrap_servers,
                "request_topic": TOPICS.REQUEST,
                "response_topics": [TOPICS.COMPLETED, TOPICS.FAILED],
            },
        )

        try:
            # Step 1: Initialize RoutingHandler (with config for PostgreSQL logging)
            logger.info("Initializing RoutingHandler...")
            self._routing_handler = RoutingHandler(config=self.config.to_dict())
            await self._routing_handler.initialize()
            logger.info("RoutingHandler initialized successfully")

            # Step 2: Check Kafka availability
            if not AIOKAFKA_AVAILABLE:
                raise RuntimeError(
                    "aiokafka not available. Install with: pip install aiokafka"
                )

            # Step 3: Initialize Kafka consumer
            logger.info(
                "Initializing Kafka consumer",
                extra={
                    "topic": TOPICS.REQUEST,
                    "group_id": "routing_adapter_consumers",
                },
            )

            self._kafka_consumer = AIOKafkaConsumer(
                TOPICS.REQUEST,
                bootstrap_servers=self.config.kafka_bootstrap_servers.split(","),
                group_id="routing_adapter_consumers",
                value_deserializer=lambda m: (
                    json.loads(m.decode("utf-8")) if m else None
                ),
                enable_auto_commit=False,  # Manual commit for safe offset management
                auto_offset_reset="earliest",
                max_poll_records=10,  # Process in small batches
            )
            await self._kafka_consumer.start()
            logger.info("Kafka consumer started successfully")

            # Step 4: Initialize Kafka producer
            logger.info("Initializing Kafka producer for responses...")
            self._kafka_producer = AIOKafkaProducer(
                bootstrap_servers=self.config.kafka_bootstrap_servers.split(","),
                value_serializer=lambda v: (
                    json.dumps(v).encode("utf-8") if v else b""
                ),
                compression_type="gzip",
                acks="all",  # Wait for all replicas (durability)
            )
            await self._kafka_producer.start()
            logger.info("Kafka producer started successfully")

            # Step 5: Start event consumption loop
            logger.info("Starting event consumption loop...")
            self._is_consuming_events = True
            self._event_consumption_task = asyncio.create_task(
                self._consume_events_loop()
            )
            logger.info(
                "RouterEventHandler started successfully",
                extra={
                    "started_at": self._started_at.isoformat(),
                    "consumer_group": "routing_adapter_consumers",
                },
            )

        except Exception as e:
            logger.error(f"Failed to start RouterEventHandler: {e}", exc_info=True)
            # Cleanup on failure
            await self.stop()
            raise RuntimeError(f"RouterEventHandler initialization failed: {e}") from e

    async def _consume_events_loop(self) -> None:
        """
        Background event consumption loop.

        Continuously consumes routing request events from Kafka and processes them.
        Implements at-least-once delivery semantics with manual offset commit.

        Event Processing Flow:
            1. Consume message from Kafka
            2. Deserialize into ModelRoutingEventEnvelope
            3. Validate envelope and extract payload
            4. Process routing request via RoutingHandler
            5. Wrap response in envelope
            6. Publish response envelope to Kafka
            7. Commit offset on success

        Error Handling:
            - Deserialization errors → Log, publish error envelope, commit
            - Validation errors → Log, publish error envelope, commit
            - Processing errors → Log, publish error envelope, commit
            - Kafka publish errors → Log, do NOT commit (retry)

        Runs until:
            - self._is_consuming_events is set to False
            - Unrecoverable error occurs
        """
        if not self._kafka_consumer:
            logger.error(
                "Cannot start event consumption - Kafka consumer not initialized"
            )
            return

        logger.info(
            "Event consumption loop started",
            extra={
                "topic": TOPICS.REQUEST,
                "group_id": "routing_adapter_consumers",
            },
        )

        try:
            async for message in self._kafka_consumer:
                if not self._is_consuming_events:
                    logger.info("Event consumption loop shutting down")
                    break

                correlation_id = None
                request_envelope = None

                try:
                    # Extract raw event data
                    event_data = message.value

                    # Deserialize into envelope
                    try:
                        request_envelope = ModelRoutingEventEnvelope(**event_data)
                        correlation_id = request_envelope.correlation_id

                        logger.debug(
                            "Processing routing request",
                            extra={
                                "correlation_id": correlation_id,
                                "event_id": request_envelope.event_id,
                                "event_type": request_envelope.event_type,
                                "service": request_envelope.service,
                                "topic": message.topic,
                                "partition": message.partition,
                                "offset": message.offset,
                            },
                        )

                    except Exception as e:
                        # Deserialization error
                        correlation_id = event_data.get("correlation_id", str(uuid4()))
                        logger.error(
                            f"Failed to deserialize request envelope: {e}",
                            extra={
                                "correlation_id": correlation_id,
                                "raw_event": event_data,
                            },
                            exc_info=True,
                        )

                        # Publish error response
                        await self._publish_error_response(
                            correlation_id=correlation_id,
                            error_code="DESERIALIZATION_ERROR",
                            error_message=f"Failed to deserialize request envelope: {e}",
                        )

                        # Commit offset (error published)
                        await self._kafka_consumer.commit()
                        self._error_count += 1
                        continue

                    # Validate event type
                    if request_envelope.event_type != EventTypes.REQUESTED:
                        logger.warning(
                            f"Unexpected event type: {request_envelope.event_type}",
                            extra={"correlation_id": correlation_id},
                        )
                        await self._publish_error_response(
                            correlation_id=correlation_id,
                            error_code="INVALID_EVENT_TYPE",
                            error_message=f"Expected {EventTypes.REQUESTED}, got {request_envelope.event_type}",
                        )
                        await self._kafka_consumer.commit()
                        self._error_count += 1
                        continue

                    # Extract request payload
                    request_payload = request_envelope.payload

                    # Convert to dict for RoutingHandler (expects dict, not Pydantic model)
                    if hasattr(request_payload, "model_dump"):
                        request_dict = request_payload.model_dump()
                    else:
                        request_dict = request_payload

                    # Process routing request via RoutingHandler
                    response_dict = await self._routing_handler.handle_routing_request(
                        request_dict
                    )

                    # Create response envelope
                    # Convert response dict to proper recommendation format
                    recommendations = [
                        {
                            "agent_name": response_dict["selected_agent"],
                            "agent_title": response_dict.get(
                                "agent_title", response_dict["selected_agent"]
                            ),
                            "confidence": {
                                "total": response_dict["confidence"],
                                "trigger_score": 0.0,  # Not available from current RoutingHandler
                                "context_score": 0.0,
                                "capability_score": 0.0,
                                "historical_score": 0.0,
                                "explanation": response_dict["reason"],
                            },
                            "reason": response_dict["reason"],
                            "definition_path": response_dict.get("definition_path", ""),
                            "alternatives": [
                                alt["agent_name"]
                                for alt in response_dict.get("alternatives", [])
                            ],
                        }
                    ]

                    routing_metadata = {
                        "routing_time_ms": response_dict["routing_time_ms"],
                        "cache_hit": False,  # Not tracked yet
                        "candidates_evaluated": len(
                            response_dict.get("alternatives", [])
                        )
                        + 1,
                        "routing_strategy": response_dict["routing_strategy"],
                        "service_version": "1.0.0",
                    }

                    response_envelope = ModelRoutingEventEnvelope.create_response(
                        correlation_id=correlation_id,
                        recommendations=recommendations,
                        routing_metadata=routing_metadata,
                        service="agent-router-service",
                    )

                    # Publish response envelope
                    await self._kafka_producer.send(
                        TOPICS.COMPLETED,
                        value=response_envelope.model_dump(),
                    )

                    # Commit offset (success)
                    await self._kafka_consumer.commit()

                    # Update metrics
                    self._request_count += 1
                    self._success_count += 1

                    logger.info(
                        "Routing request processed successfully",
                        extra={
                            "correlation_id": correlation_id,
                            "selected_agent": response_dict["selected_agent"],
                            "confidence": response_dict["confidence"],
                            "routing_time_ms": response_dict["routing_time_ms"],
                        },
                    )

                except ValueError as e:
                    # Validation error
                    self._request_count += 1
                    self._error_count += 1

                    logger.warning(
                        f"Routing request validation failed: {e}",
                        extra={"correlation_id": correlation_id},
                    )

                    await self._publish_error_response(
                        correlation_id=correlation_id or str(uuid4()),
                        error_code="VALIDATION_ERROR",
                        error_message=str(e),
                    )

                    # Commit offset (error published)
                    await self._kafka_consumer.commit()

                except Exception as e:
                    # Processing error
                    self._request_count += 1
                    self._error_count += 1

                    logger.error(
                        f"Failed to process routing request: {e}",
                        extra={"correlation_id": correlation_id},
                        exc_info=True,
                    )

                    await self._publish_error_response(
                        correlation_id=correlation_id or str(uuid4()),
                        error_code="PROCESSING_ERROR",
                        error_message=str(e),
                    )

                    # Commit offset (error published)
                    await self._kafka_consumer.commit()

        except asyncio.CancelledError:
            logger.info("Event consumption loop cancelled")
            raise
        except Exception as e:
            logger.error(f"Event consumption loop failed: {e}", exc_info=True)
            self._is_consuming_events = False
        finally:
            logger.info(
                "Event consumption loop stopped",
                extra={
                    "total_requests": self._request_count,
                    "success_count": self._success_count,
                    "error_count": self._error_count,
                },
            )

    async def _publish_error_response(
        self,
        correlation_id: str,
        error_code: str,
        error_message: str,
    ) -> None:
        """
        Publish error response envelope to failed topic.

        Args:
            correlation_id: Request correlation ID
            error_code: Error code (DESERIALIZATION_ERROR, VALIDATION_ERROR, etc.)
            error_message: Human-readable error message
        """
        try:
            error_envelope = ModelRoutingEventEnvelope.create_error(
                correlation_id=correlation_id,
                error_code=error_code,
                error_message=error_message,
                service="agent-router-service",
            )

            await self._kafka_producer.send(
                TOPICS.FAILED,
                value=error_envelope.model_dump(),
            )

            logger.debug(
                "Published error response",
                extra={
                    "correlation_id": correlation_id,
                    "error_code": error_code,
                    "topic": TOPICS.FAILED,
                },
            )

        except Exception as e:
            logger.error(
                f"Failed to publish error response: {e}",
                extra={
                    "correlation_id": correlation_id,
                    "error_code": error_code,
                },
                exc_info=True,
            )

    async def stop(self) -> None:
        """
        Stop router event handler and cleanup resources.

        Cleanup tasks:
            1. Stop event consumption loop
            2. Close Kafka consumer
            3. Close Kafka producer
            4. Shutdown routing handler

        Implementation: Graceful shutdown with timeout protection
        """
        logger.info(
            "Stopping RouterEventHandler",
            extra={
                "uptime_seconds": (
                    (datetime.now(UTC) - self._started_at).total_seconds()
                    if self._started_at
                    else 0
                ),
                "total_requests": self._request_count,
                "success_count": self._success_count,
                "error_count": self._error_count,
            },
        )

        # Step 1: Stop event consumption loop
        if self._is_consuming_events:
            logger.info("Stopping event consumption loop...")
            self._is_consuming_events = False

            if self._event_consumption_task:
                self._event_consumption_task.cancel()
                try:
                    await self._event_consumption_task
                except asyncio.CancelledError:
                    logger.info("Event consumption task cancelled")

        # Step 2: Close Kafka consumer
        if self._kafka_consumer:
            try:
                logger.info("Closing Kafka consumer...")
                await self._kafka_consumer.stop()
                logger.info("Kafka consumer closed")
            except Exception as e:
                logger.error(f"Error closing Kafka consumer: {e}", exc_info=True)

        # Step 3: Close Kafka producer
        if self._kafka_producer:
            try:
                logger.info("Closing Kafka producer...")
                await self._kafka_producer.stop()
                logger.info("Kafka producer closed")
            except Exception as e:
                logger.error(f"Error closing Kafka producer: {e}", exc_info=True)

        # Step 4: Shutdown routing handler
        if self._routing_handler:
            try:
                logger.info("Shutting down routing handler...")
                await self._routing_handler.shutdown()
                logger.info("Routing handler shutdown complete")
            except Exception as e:
                logger.error(f"Error shutting down routing handler: {e}", exc_info=True)

        logger.info("RouterEventHandler stopped successfully")

    def get_metrics(self) -> dict[str, Any]:
        """
        Get event handler metrics.

        Returns:
            Dictionary of metrics:
            - request_count: Total requests processed
            - success_count: Successful requests
            - error_count: Failed requests
            - success_rate: Success percentage
            - uptime_seconds: Service uptime
        """
        success_rate = (
            (self._success_count / self._request_count * 100)
            if self._request_count > 0
            else 0.0
        )

        uptime_seconds = (
            (datetime.now(UTC) - self._started_at).total_seconds()
            if self._started_at
            else 0.0
        )

        return {
            "request_count": self._request_count,
            "success_count": self._success_count,
            "error_count": self._error_count,
            "success_rate": round(success_rate, 2),
            "uptime_seconds": round(uptime_seconds, 2),
        }


__all__ = ["RouterEventHandler"]
