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
    1. RouterEventHandler consumes routing request from Kafka
    2. Process with RoutingHandler → AgentRouter
    3. Publish response to Kafka (completed or failed)
    4. Log routing decision to PostgreSQL (via agent-tracking events)

Implementation: Phase 2 - Event-Driven Routing Adapter with RouterEventHandler
"""

import asyncio
import logging
import signal
from datetime import UTC, datetime

from aiohttp import web

from .config import get_config
from .router_event_handler import RouterEventHandler

logger = logging.getLogger(__name__)


class RoutingAdapterService:
    """
    Routing Adapter Service.

    Event-driven service for agent routing requests using Kafka message bus.
    Uses RouterEventHandler for event processing with envelope pattern.
    """

    def __init__(self):
        """Initialize routing adapter service."""
        # Configuration
        self.config = get_config()

        # Dependencies
        self._router_event_handler: RouterEventHandler | None = None

        # Service state
        self._is_running = False

        # Health status
        self._health_status = {
            "status": "starting",
            "timestamp": datetime.now(UTC).isoformat(),
            "components": {
                "router_event_handler": "initializing",
            },
        }

        # Metrics
        self._started_at: datetime | None = None

    async def initialize(self) -> None:
        """
        Initialize service dependencies.

        Process:
            1. Initialize RouterEventHandler (which handles Kafka and RoutingHandler)
            2. Start RouterEventHandler (starts event consumption loop)
            3. Update health status

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
            # Step 1: Initialize RouterEventHandler
            logger.info("Initializing RouterEventHandler...")
            self._router_event_handler = RouterEventHandler()
            await self._router_event_handler.start()
            self._health_status["components"]["router_event_handler"] = "healthy"
            logger.info("RouterEventHandler initialized successfully")

            # Step 2: Update health status
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

    async def shutdown(self) -> None:
        """
        Graceful shutdown of routing adapter service.

        Cleanup tasks:
            1. Stop RouterEventHandler (which handles Kafka and RoutingHandler cleanup)
        """
        logger.info(
            "Shutting down Routing Adapter Service",
            extra={
                "uptime_seconds": (
                    (datetime.now(UTC) - self._started_at).total_seconds()
                    if self._started_at
                    else 0
                ),
            },
        )

        self._is_running = False

        # Step 1: Stop RouterEventHandler
        if self._router_event_handler:
            try:
                logger.info("Stopping RouterEventHandler...")
                await self._router_event_handler.stop()
                logger.info("RouterEventHandler stopped successfully")
            except Exception as e:
                logger.error(f"Error stopping RouterEventHandler: {e}", exc_info=True)

        logger.info("Routing Adapter Service shutdown complete")

    # HTTP Health Check Handler
    async def health_check_handler(self, request: web.Request) -> web.Response:
        """
        HTTP health check endpoint handler.

        Returns:
            JSON response with health status and metrics from RouterEventHandler
        """
        # Get metrics from RouterEventHandler
        metrics = (
            self._router_event_handler.get_metrics()
            if self._router_event_handler
            else {}
        )

        health_response = {
            **self._health_status,
            "uptime_seconds": (
                (datetime.now(UTC) - self._started_at).total_seconds()
                if self._started_at
                else 0
            ),
            "metrics": metrics,
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
