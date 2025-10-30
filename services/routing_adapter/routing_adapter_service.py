"""
Routing Adapter Service.

Event-driven service that consumes routing requests from Kafka, processes them
using AgentRouter, and publishes routing responses back to Kafka.

Follows ONEX v2.0 event-driven architecture patterns:
- Container-based dependency injection
- Async/await throughout
- Graceful shutdown handling
- Health check endpoints
- Structured logging with correlation IDs
- Circuit breaker for resilience

Event Flow:
    1. Consume routing request from Kafka (topic: dev.routing-adapter.routing.request.v1)
    2. Process with RoutingHandler → AgentRouter
    3. Publish response to Kafka (topic: dev.routing-adapter.routing.response.v1)
    4. Log routing decision to PostgreSQL (via agent-tracking events)

Implementation: Phase 1 - Event-Driven Routing Adapter
"""

import asyncio
import json
import logging
import signal
from datetime import UTC, datetime
from typing import Any, Optional
from uuid import uuid4

from aiohttp import web

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

logger = logging.getLogger(__name__)


class RoutingAdapterService:
    """
    Routing Adapter Service.

    Event-driven service for agent routing requests using Kafka message bus.
    """

    def __init__(self):
        """Initialize routing adapter service."""
        # Configuration
        self.config = get_config()

        # Dependencies
        self._routing_handler: Optional[RoutingHandler] = None
        self._kafka_consumer: Optional[AIOKafkaConsumer] = None
        self._kafka_producer: Optional[AIOKafkaProducer] = None

        # Background tasks
        self._event_consumption_task: Optional[asyncio.Task] = None
        self._health_check_task: Optional[asyncio.Task] = None
        self._is_consuming_events = False
        self._is_running = False

        # Health status
        self._health_status = {
            "status": "starting",
            "timestamp": datetime.now(UTC).isoformat(),
            "components": {
                "routing_handler": "initializing",
                "kafka_consumer": "initializing",
                "kafka_producer": "initializing",
            },
        }

        # Metrics
        self._started_at: Optional[datetime] = None
        self._request_count = 0
        self._success_count = 0
        self._error_count = 0

    async def initialize(self) -> None:
        """
        Initialize service dependencies.

        Process:
            1. Initialize RoutingHandler with AgentRouter
            2. Initialize Kafka consumer for routing requests
            3. Initialize Kafka producer for routing responses
            4. Start background event consumption loop
            5. Start health check loop

        Raises:
            RuntimeError: If initialization fails
        """
        self._started_at = datetime.now(UTC)

        logger.info(
            "Initializing Routing Adapter Service",
            extra={
                "kafka_bootstrap_servers": self.config.kafka_bootstrap_servers,
                "service_port": self.config.service_port,
            },
        )

        try:
            # Step 1: Initialize RoutingHandler
            logger.info("Initializing RoutingHandler...")
            self._routing_handler = RoutingHandler()
            await self._routing_handler.initialize()
            self._health_status["components"]["routing_handler"] = "healthy"
            logger.info("RoutingHandler initialized successfully")

            # Step 2: Initialize Kafka consumer
            if not AIOKAFKA_AVAILABLE:
                raise RuntimeError(
                    "aiokafka not available. Install with: pip install aiokafka"
                )

            logger.info("Initializing Kafka consumer...")
            self._kafka_consumer = AIOKafkaConsumer(
                self.config.topic_routing_request,
                bootstrap_servers=self.config.kafka_bootstrap_servers.split(","),
                group_id="routing_adapter_consumers",
                value_deserializer=lambda m: (
                    json.loads(m.decode("utf-8")) if m else None
                ),
                enable_auto_commit=False,  # Manual commit for safe offset management
                auto_offset_reset="earliest",
            )
            await self._kafka_consumer.start()
            self._health_status["components"]["kafka_consumer"] = "healthy"
            logger.info(
                "Kafka consumer started",
                extra={
                    "topics": [self.config.topic_routing_request],
                    "group_id": "routing_adapter_consumers",
                },
            )

            # Step 3: Initialize Kafka producer
            logger.info("Initializing Kafka producer...")
            self._kafka_producer = AIOKafkaProducer(
                bootstrap_servers=self.config.kafka_bootstrap_servers.split(","),
                value_serializer=lambda v: json.dumps(v).encode("utf-8") if v else b"",
            )
            await self._kafka_producer.start()
            self._health_status["components"]["kafka_producer"] = "healthy"
            logger.info("Kafka producer started")

            # Step 4: Start background event consumption loop
            logger.info("Starting event consumption loop...")
            self._is_consuming_events = True
            self._event_consumption_task = asyncio.create_task(
                self._consume_events_loop()
            )
            logger.info("Event consumption loop started")

            # Step 5: Update health status
            self._health_status["status"] = "healthy"
            self._health_status["timestamp"] = datetime.now(UTC).isoformat()
            self._is_running = True

            logger.info(
                "Routing Adapter Service initialized successfully",
                extra={
                    "components": self._health_status["components"],
                    "started_at": self._started_at.isoformat(),
                },
            )

        except Exception as e:
            logger.error(f"Service initialization failed: {e}", exc_info=True)
            self._health_status["status"] = "unhealthy"
            self._health_status["error"] = str(e)
            raise RuntimeError(f"Service initialization failed: {e}") from e

    async def _consume_events_loop(self) -> None:
        """
        Background event consumption loop.

        Continuously consumes routing request events from Kafka and processes them.
        Implements at-least-once delivery semantics with manual offset commit.

        Event Processing:
            1. Consume routing request event
            2. Call RoutingHandler.handle_routing_request()
            3. Publish routing response event
            4. Commit offset on success
            5. Publish failure event on error (no commit)
        """
        if not self._kafka_consumer:
            logger.error(
                "Cannot start event consumption - Kafka consumer not initialized"
            )
            return

        logger.info(
            "Event consumption loop started",
            extra={
                "topic": self.config.topic_routing_request,
                "group_id": "routing_adapter_consumers",
            },
        )

        try:
            async for message in self._kafka_consumer:
                if not self._is_consuming_events:
                    logger.info("Event consumption loop shutting down")
                    break

                correlation_id = None
                try:
                    # Extract event
                    event = message.value
                    correlation_id = event.get("correlation_id", str(uuid4()))

                    logger.debug(
                        "Processing routing request",
                        extra={
                            "correlation_id": correlation_id,
                            "topic": message.topic,
                            "partition": message.partition,
                            "offset": message.offset,
                        },
                    )

                    # Process routing request
                    response = await self._routing_handler.handle_routing_request(event)

                    # Publish response
                    await self._kafka_producer.send(
                        self.config.topic_routing_response,
                        value=response,
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
                            "selected_agent": response.get("selected_agent"),
                            "confidence": response.get("confidence"),
                        },
                    )

                except Exception as e:
                    # Processing error
                    self._request_count += 1
                    self._error_count += 1

                    logger.error(
                        f"Failed to process routing request: {e}",
                        extra={"correlation_id": correlation_id},
                        exc_info=True,
                    )

                    # Publish failure event
                    try:
                        failure_event = {
                            "correlation_id": correlation_id or str(uuid4()),
                            "error": str(e),
                            "error_type": type(e).__name__,
                            "timestamp": datetime.now(UTC).isoformat(),
                            "original_event": event if "event" in locals() else None,
                        }
                        await self._kafka_producer.send(
                            self.config.topic_routing_failed,
                            value=failure_event,
                        )
                        # Commit offset (failure published to DLQ)
                        await self._kafka_consumer.commit()
                    except Exception as publish_error:
                        logger.error(
                            f"Failed to publish failure event: {publish_error}",
                            extra={"correlation_id": correlation_id},
                            exc_info=True,
                        )
                        # Do NOT commit offset - will be redelivered

        except asyncio.CancelledError:
            logger.info("Event consumption loop cancelled")
            raise
        except Exception as e:
            logger.error(f"Event consumption loop failed: {e}", exc_info=True)
            self._health_status["status"] = "unhealthy"
            self._health_status["error"] = f"Event consumption failed: {e}"

    async def shutdown(self) -> None:
        """
        Graceful shutdown of routing adapter service.

        Cleanup tasks:
            1. Stop event consumption loop
            2. Close Kafka consumer
            3. Close Kafka producer
            4. Shutdown routing handler
        """
        logger.info(
            "Shutting down Routing Adapter Service",
            extra={
                "uptime_seconds": (
                    (datetime.now(UTC) - self._started_at).total_seconds()
                    if self._started_at
                    else 0
                ),
                "total_requests": self._request_count,
            },
        )

        self._is_running = False

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

        logger.info("Routing Adapter Service shutdown complete")

    # HTTP Health Check Handler
    async def health_check_handler(self, request: web.Request) -> web.Response:
        """
        HTTP health check endpoint handler.

        Returns:
            JSON response with health status and metrics
        """
        # Update metrics
        metrics = self._routing_handler.get_metrics() if self._routing_handler else {}

        health_response = {
            **self._health_status,
            "uptime_seconds": (
                (datetime.now(UTC) - self._started_at).total_seconds()
                if self._started_at
                else 0
            ),
            "metrics": {
                **metrics,
                "total_requests": self._request_count,
                "success_count": self._success_count,
                "error_count": self._error_count,
            },
        }

        status_code = 200 if self._health_status["status"] == "healthy" else 503

        return web.json_response(health_response, status=status_code)


async def main():
    """
    Main entry point for routing adapter service.

    Sets up HTTP server for health checks and starts event consumption.
    Handles graceful shutdown on SIGINT/SIGTERM.
    """
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger.info("Starting Routing Adapter Service")

    # Create service
    service = RoutingAdapterService()

    # Initialize service
    await service.initialize()

    # Setup HTTP server for health checks
    app = web.Application()
    app.router.add_get("/health", service.health_check_handler)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(
        runner, host=service.config.service_host, port=service.config.service_port
    )
    await site.start()

    logger.info(
        f"HTTP health check server started at "
        f"http://{service.config.service_host}:{service.config.service_port}/health"
    )

    # Setup signal handlers for graceful shutdown
    def signal_handler():
        logger.info("Received shutdown signal")
        asyncio.create_task(service.shutdown())

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    # Keep running until shutdown
    try:
        while service._is_running:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    finally:
        await service.shutdown()
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
