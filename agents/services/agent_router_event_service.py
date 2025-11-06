#!/usr/bin/env python3
"""
Agent Router Event Service - Kafka Consumer
============================================

Kafka-based event consumer for agent routing requests. Replaces HTTP-based
agent_router_service.py with event-driven architecture.

Event Flow:
1. Consume from agent.routing.requested.v1
2. Route using existing AgentRouter (NO changes to routing logic)
3. Publish to agent.routing.completed.v1 (success) or agent.routing.failed.v1 (error)
4. Log to agent_routing_decisions table (PostgreSQL)

Features:
- Event-driven architecture via Kafka
- Correlation ID tracking for request/response matching
- Database logging with retry and exponential backoff
- Graceful shutdown on SIGTERM
- Complete observability (same as HTTP service)
- Reuses existing AgentRouter logic (DRY principle)

Performance Targets:
- Response time: <100ms p95
- Throughput: 100+ requests/second
- Success rate: >95%

Created: 2025-10-30
Reference: agent_router_service.py (HTTP version)
"""

import asyncio
import json
import logging
import os
import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Kafka imports
try:
    from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False
    logging.error("aiokafka not available. Install with: pip install aiokafka")

# PostgreSQL imports
try:
    import asyncpg

    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False
    logging.error("asyncpg not available. Install with: pip install asyncpg")

# HTTP server for health checks
try:
    from aiohttp import web

    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    logging.error("aiohttp not available. Install with: pip install aiohttp")

# Add lib directory to Python path for AgentRouter imports
lib_path = Path(__file__).parent.parent / "lib"
sys.path.insert(0, str(lib_path))

try:
    from agent_router import AgentRouter
except ImportError as e:
    logging.error(f"Failed to import AgentRouter: {e}")
    logging.error(f"Python path: {sys.path}")
    raise

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


class PostgresLogger:
    """
    Lightweight PostgreSQL logger for routing decisions.

    Provides non-blocking async logging to agent_routing_decisions table
    with retry logic and graceful degradation.
    """

    def __init__(
        self,
        host: str,
        port: int,
        database: str,
        user: str,
        password: str,
        pool_min_size: int = 2,
        pool_max_size: int = 10,
    ):
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.pool_min_size = pool_min_size
        self.pool_max_size = pool_max_size

        self._pool: Optional[asyncpg.Pool] = None
        self._initialized = False

        # Metrics
        self._log_count = 0
        self._success_count = 0
        self._error_count = 0

    async def initialize(self) -> None:
        """Initialize database connection pool."""
        if self._initialized:
            logger.warning("PostgresLogger already initialized")
            return

        if not ASYNCPG_AVAILABLE:
            logger.error("asyncpg not available - database logging disabled")
            return

        logger.info(
            f"Initializing PostgreSQL connection pool (host: {self.host}:{self.port}, db: {self.database})"
        )

        try:
            self._pool = await asyncpg.create_pool(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password,
                min_size=self.pool_min_size,
                max_size=self.pool_max_size,
                command_timeout=10.0,
                timeout=5.0,
            )

            # Test connection
            async with self._pool.acquire() as conn:
                await conn.fetchval("SELECT 1")

            self._initialized = True
            logger.info("PostgreSQL connection pool initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize PostgreSQL pool: {e}", exc_info=True)
            self._initialized = False

    async def close(self) -> None:
        """Close database connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            self._initialized = False
            logger.info("PostgreSQL connection pool closed")

    async def log_routing_decision(
        self,
        user_request: str,
        selected_agent: str,
        confidence_score: float,
        routing_strategy: str,
        routing_time_ms: float,
        correlation_id: Optional[str] = None,
        alternatives: Optional[List[Dict[str, Any]]] = None,
        reasoning: Optional[str] = None,
        max_retries: int = 3,
    ) -> Optional[str]:
        """
        Log routing decision to database with retry logic.

        Non-blocking - will not raise exceptions even if logging fails.

        Args:
            user_request: User's request text
            selected_agent: Selected agent name
            confidence_score: Confidence score (0.0-1.0)
            routing_strategy: Strategy used for routing
            routing_time_ms: Time taken for routing in milliseconds
            correlation_id: Correlation ID for traceability
            alternatives: Alternative agent recommendations
            reasoning: Reasoning for selection
            max_retries: Maximum retry attempts (default: 3)

        Returns:
            Record ID on success, None on failure
        """
        if not self._initialized or not self._pool:
            logger.debug("PostgresLogger not initialized - skipping database log")
            return None

        self._log_count += 1

        # Prepare data
        alternatives_json = json.dumps(alternatives or [])
        routing_time_int = int(round(routing_time_ms))

        insert_sql = """
            INSERT INTO agent_routing_decisions (
                correlation_id,
                user_request,
                selected_agent,
                confidence_score,
                alternatives,
                reasoning,
                routing_strategy,
                routing_time_ms,
                created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id
        """

        # Retry loop with exponential backoff
        retry_delay = 0.1

        for attempt in range(max_retries):
            try:
                async with self._pool.acquire() as conn:
                    record_id = await conn.fetchval(
                        insert_sql,
                        correlation_id,
                        user_request,
                        selected_agent,
                        confidence_score,
                        alternatives_json,
                        reasoning,
                        routing_strategy,
                        routing_time_int,
                        datetime.now(UTC),
                    )

                    self._success_count += 1
                    logger.debug(
                        f"Routing decision logged (record_id: {record_id}, agent: {selected_agent})"
                    )
                    return str(record_id)

            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(
                        f"Logging failed (attempt {attempt + 1}/{max_retries}), retrying in {retry_delay}s: {e}"
                    )
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    self._error_count += 1
                    logger.error(
                        f"Logging failed after {max_retries} attempts: {e}",
                        exc_info=True,
                    )

        return None

    def get_stats(self) -> Dict[str, int]:
        """Get logging statistics."""
        return {
            "total_logs": self._log_count,
            "successful_logs": self._success_count,
            "failed_logs": self._error_count,
        }


class AgentRouterEventService:
    """
    Kafka consumer service for agent routing events.

    Consumes routing requests from Kafka, processes using AgentRouter,
    publishes responses, and logs decisions to PostgreSQL.
    """

    # Kafka topic names
    TOPIC_REQUEST = "agent.routing.requested.v1"
    TOPIC_COMPLETED = "agent.routing.completed.v1"
    TOPIC_FAILED = "agent.routing.failed.v1"

    def __init__(
        self,
        bootstrap_servers: str,
        consumer_group_id: str = "agent-router-service",
        registry_path: Optional[str] = None,
        db_host: str = "192.168.86.200",
        db_port: int = 5436,
        db_name: str = "omninode_bridge",
        db_user: str = "postgres",
        db_password: str = "",
        health_check_port: int = 8070,
    ):
        """
        Initialize agent router event service.

        Args:
            bootstrap_servers: Kafka bootstrap servers
            consumer_group_id: Consumer group ID
            registry_path: Path to agent registry YAML
            db_host: PostgreSQL host
            db_port: PostgreSQL port
            db_name: PostgreSQL database name
            db_user: PostgreSQL user
            db_password: PostgreSQL password
            health_check_port: Port for HTTP health check endpoint
        """
        if not KAFKA_AVAILABLE:
            raise RuntimeError("aiokafka not available - cannot start event service")

        self.bootstrap_servers = bootstrap_servers
        self.consumer_group_id = consumer_group_id
        self.health_check_port = health_check_port

        # Default registry path
        if registry_path is None:
            registry_path = str(
                Path.home() / ".claude" / "agent-definitions" / "agent-registry.yaml"
            )
        self.registry_path = registry_path

        # Database config
        self.db_config = {
            "host": db_host,
            "port": db_port,
            "database": db_name,
            "user": db_user,
            "password": db_password,
        }

        # Components
        self._router: Optional[AgentRouter] = None
        self._producer: Optional[AIOKafkaProducer] = None
        self._consumer: Optional[AIOKafkaConsumer] = None
        self._postgres_logger: Optional[PostgresLogger] = None
        self._health_app: Optional[web.Application] = None
        self._health_runner: Optional[web.AppRunner] = None
        self._shutdown_event = asyncio.Event()
        self._started = False

        # Metrics
        self._requests_processed = 0
        self._requests_succeeded = 0
        self._requests_failed = 0
        self._total_routing_time_ms = 0.0
        self._start_time = time.time()

        self.logger = logging.getLogger(__name__)

    async def start(self) -> None:
        """
        Start the event service.

        Initializes AgentRouter, Kafka producer/consumer, PostgreSQL logger, and health check server.
        """
        if self._started:
            self.logger.warning("Service already started")
            return

        self.logger.info("=" * 60)
        self.logger.info("Agent Router Event Service Starting")
        self.logger.info("=" * 60)

        # Initialize AgentRouter
        if not Path(self.registry_path).exists():
            raise FileNotFoundError(f"Registry not found: {self.registry_path}")

        self.logger.info(f"Loading agent registry from: {self.registry_path}")
        self._router = AgentRouter(self.registry_path, cache_ttl=3600)
        agent_count = len(self._router.registry.get("agents", {}))
        self.logger.info(f"Loaded {agent_count} agents successfully")

        # Initialize PostgreSQL logger
        self._postgres_logger = PostgresLogger(**self.db_config)
        await self._postgres_logger.initialize()

        # Initialize Kafka producer
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self.bootstrap_servers,
            compression_type="gzip",
            linger_ms=20,
            acks="all",
            api_version="auto",
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
        await self._producer.start()
        self.logger.info("Kafka producer started")

        # Initialize Kafka consumer
        self._consumer = AIOKafkaConsumer(
            self.TOPIC_REQUEST,
            bootstrap_servers=self.bootstrap_servers,
            group_id=self.consumer_group_id,
            enable_auto_commit=True,
            auto_offset_reset="latest",
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        )
        await self._consumer.start()
        self.logger.info(f"Kafka consumer started (group: {self.consumer_group_id})")

        # Start health check server
        if AIOHTTP_AVAILABLE:
            await self._start_health_server()
        else:
            self.logger.warning("aiohttp not available - health check server disabled")

        self._started = True
        self.logger.info("=" * 60)
        self.logger.info("Service ready - waiting for routing requests")
        self.logger.info(f"  Consuming from: {self.TOPIC_REQUEST}")
        self.logger.info(
            f"  Publishing to: {self.TOPIC_COMPLETED}, {self.TOPIC_FAILED}"
        )
        self.logger.info(
            f"  Health check: http://localhost:{self.health_check_port}/health"
        )
        self.logger.info("=" * 60)

    async def _start_health_server(self) -> None:
        """Start HTTP health check server."""
        try:
            # Create health check endpoint
            async def health_handler(request):
                """Health check endpoint handler."""
                return web.json_response(
                    {
                        "status": "healthy",
                        "service": "router-consumer",
                        "uptime_seconds": int(time.time() - self._start_time),
                        "metrics": {
                            "requests_processed": self._requests_processed,
                            "requests_succeeded": self._requests_succeeded,
                            "requests_failed": self._requests_failed,
                            "success_rate": (
                                self._requests_succeeded / self._requests_processed
                                if self._requests_processed > 0
                                else 0.0
                            ),
                            "average_routing_time_ms": (
                                self._total_routing_time_ms / self._requests_processed
                                if self._requests_processed > 0
                                else 0.0
                            ),
                        },
                    }
                )

            # Create aiohttp application
            self._health_app = web.Application()
            self._health_app.router.add_get("/health", health_handler)

            # Create and start runner
            self._health_runner = web.AppRunner(self._health_app)
            await self._health_runner.setup()

            # Start site (bind to all interfaces for Docker container accessibility)
            site = web.TCPSite(
                self._health_runner, "0.0.0.0", self.health_check_port  # noqa: S104
            )
            await site.start()

            self.logger.info(
                f"Health check server started on port {self.health_check_port}"
            )

        except Exception as e:
            self.logger.error(
                f"Failed to start health check server: {e}", exc_info=True
            )

    async def stop(self) -> None:
        """Stop the event service gracefully."""
        if not self._started:
            return

        self.logger.info("Stopping agent router event service...")
        self._shutdown_event.set()

        # Stop health check server
        if self._health_runner:
            await self._health_runner.cleanup()
            self.logger.info("Health check server stopped")

        # Stop consumer
        if self._consumer:
            await self._consumer.stop()
            self.logger.info("Kafka consumer stopped")

        # Stop producer
        if self._producer:
            await self._producer.stop()
            self.logger.info("Kafka producer stopped")

        # Close PostgreSQL logger
        if self._postgres_logger:
            await self._postgres_logger.close()

        self._started = False

        # Log final statistics
        uptime = time.time() - self._start_time
        self.logger.info("=" * 60)
        self.logger.info("Agent Router Event Service Stopped")
        self.logger.info(f"  Uptime: {uptime:.1f}s")
        self.logger.info(f"  Requests processed: {self._requests_processed}")
        self.logger.info(f"  Successful: {self._requests_succeeded}")
        self.logger.info(f"  Failed: {self._requests_failed}")
        if self._requests_processed > 0:
            avg_time = self._total_routing_time_ms / self._requests_processed
            self.logger.info(f"  Average routing time: {avg_time:.1f}ms")
        if self._postgres_logger:
            stats = self._postgres_logger.get_stats()
            self.logger.info(f"  Database logs: {stats}")
        self.logger.info("=" * 60)

    async def consume_routing_requests(self) -> None:
        """
        Main consumer loop.

        Continuously consumes routing requests from Kafka, processes them,
        and publishes responses.
        """
        if not self._consumer:
            raise RuntimeError("Consumer not initialized. Call start() first.")

        self.logger.info("Starting routing request consumer loop")

        try:
            async for msg in self._consumer:
                if self._shutdown_event.is_set():
                    break

                try:
                    # Parse request envelope
                    request = msg.value
                    correlation_id = request.get("correlation_id")
                    user_request = request.get("payload", {}).get("user_request", "")
                    context = request.get("payload", {}).get("context", {})
                    options = request.get("payload", {}).get("options", {})

                    if not correlation_id or not user_request:
                        self.logger.warning(
                            f"Invalid request (missing correlation_id or user_request): {request}"
                        )
                        continue

                    self.logger.debug(
                        f"Processing routing request (correlation_id: {correlation_id}, request: {user_request[:100]}...)"
                    )

                    # Route request
                    start_time = time.time()
                    await self._handle_routing_request(
                        correlation_id=correlation_id,
                        user_request=user_request,
                        context=context,
                        options=options,
                    )
                    routing_time_ms = (time.time() - start_time) * 1000

                    # Update metrics
                    self._requests_processed += 1
                    self._total_routing_time_ms += routing_time_ms

                except Exception as e:
                    self.logger.error(f"Error processing message: {e}", exc_info=True)
                    continue

        except asyncio.CancelledError:
            self.logger.info("Consumer loop cancelled")
            raise

        except Exception as e:
            self.logger.error(f"Consumer loop failed: {e}", exc_info=True)
            raise

        finally:
            self.logger.info("Routing request consumer loop stopped")

    async def _handle_routing_request(
        self,
        correlation_id: str,
        user_request: str,
        context: Dict[str, Any],
        options: Dict[str, Any],
    ) -> None:
        """
        Handle a single routing request.

        Routes using AgentRouter, publishes response, and logs to database.

        Args:
            correlation_id: Request correlation ID
            user_request: User's request text
            context: Execution context
            options: Routing options
        """
        start_time = time.time()

        try:
            # Extract routing options
            max_recommendations = options.get("max_recommendations", 5)

            # Route using AgentRouter
            if not self._router:
                raise RuntimeError("AgentRouter not initialized")

            recommendations = self._router.route(
                user_request=user_request,
                context=context,
                max_recommendations=max_recommendations,
            )

            routing_time_ms = (time.time() - start_time) * 1000

            # Handle no recommendations (fallback)
            if not recommendations:
                self.logger.warning(
                    f"No recommendations for request (correlation_id: {correlation_id})"
                )
                recommendations = [self._create_fallback_recommendation()]

            # Primary recommendation
            primary = recommendations[0]

            # Build response envelope
            response_envelope = {
                "correlation_id": correlation_id,
                "event_type": "AGENT_ROUTING_COMPLETED",
                "payload": {
                    "recommendations": [
                        {
                            "agent_name": rec.agent_name,
                            "agent_title": rec.agent_title,
                            "confidence": {
                                "total": rec.confidence.total,
                                "trigger_score": rec.confidence.trigger_score,
                                "context_score": rec.confidence.context_score,
                                "capability_score": rec.confidence.capability_score,
                                "historical_score": rec.confidence.historical_score,
                                "explanation": rec.confidence.explanation,
                            },
                            "reason": rec.reason,
                            "definition_path": rec.definition_path,
                        }
                        for rec in recommendations
                    ],
                    "routing_metadata": {
                        "routing_time_ms": routing_time_ms,
                        "cache_hit": False,  # TODO: Get from router cache stats
                    },
                },
                "timestamp": datetime.now(UTC).isoformat(),
            }

            # Publish completed event
            if self._producer:
                await self._producer.send_and_wait(
                    self.TOPIC_COMPLETED, response_envelope
                )

            # Log to database
            if self._postgres_logger:
                await self._postgres_logger.log_routing_decision(
                    user_request=user_request,
                    selected_agent=primary.agent_name,
                    confidence_score=primary.confidence.total,
                    routing_strategy="enhanced_fuzzy_matching",  # TODO: Get from router
                    routing_time_ms=routing_time_ms,
                    correlation_id=correlation_id,
                    alternatives=[
                        {
                            "agent_name": rec.agent_name,
                            "confidence": rec.confidence.total,
                        }
                        for rec in recommendations[1:]
                    ],
                    reasoning=primary.reason,
                )

            self._requests_succeeded += 1
            self.logger.info(
                f"Routing completed (correlation_id: {correlation_id}, agent: {primary.agent_name}, confidence: {primary.confidence.total:.2%}, time: {routing_time_ms:.1f}ms)"
            )

        except Exception as e:
            self._requests_failed += 1
            routing_time_ms = (time.time() - start_time) * 1000

            self.logger.error(
                f"Routing failed (correlation_id: {correlation_id}): {e}",
                exc_info=True,
            )

            # Publish failed event
            if self._producer:
                error_envelope = {
                    "correlation_id": correlation_id,
                    "event_type": "AGENT_ROUTING_FAILED",
                    "payload": {
                        "error_code": "ROUTING_ERROR",
                        "error_message": str(e),
                        "routing_time_ms": routing_time_ms,
                    },
                    "timestamp": datetime.now(UTC).isoformat(),
                }
                try:
                    await self._producer.send_and_wait(
                        self.TOPIC_FAILED, error_envelope
                    )
                except Exception as publish_error:
                    self.logger.error(f"Failed to publish error event: {publish_error}")

    def _create_fallback_recommendation(self):
        """Create fallback recommendation when routing fails."""
        from agent_router import AgentRecommendation
        from confidence_scorer import ConfidenceScore

        return AgentRecommendation(
            agent_name="polymorphic-agent",
            agent_title="Polymorphic Agent (Fallback)",
            confidence=ConfidenceScore(
                total=0.5,
                trigger_score=0.5,
                context_score=0.5,
                capability_score=0.5,
                historical_score=0.5,
                explanation="Fallback to polymorphic-agent (routing failed)",
            ),
            reason="Routing failed - using fallback agent",
            definition_path=str(
                Path.home() / ".claude" / "agent-definitions" / "polymorphic-agent.yaml"
            ),
        )


async def main():
    """Main entry point for the service."""
    # Load configuration from environment
    bootstrap_servers = os.getenv(
        "KAFKA_BOOTSTRAP_SERVERS", "omninode-bridge-redpanda:9092"
    )
    consumer_group_id = os.getenv("KAFKA_GROUP_ID", "agent-router-service")
    registry_path = os.getenv("REGISTRY_PATH")
    health_check_port = int(os.getenv("HEALTH_CHECK_PORT", "8070"))

    # PostgreSQL configuration
    db_config = {
        "db_host": os.getenv("POSTGRES_HOST", "192.168.86.200"),
        "db_port": int(os.getenv("POSTGRES_PORT", "5436")),
        "db_name": os.getenv("POSTGRES_DATABASE", "omninode_bridge"),
        "db_user": os.getenv("POSTGRES_USER", "postgres"),
        "db_password": os.getenv("POSTGRES_PASSWORD", ""),
    }

    # Create service
    service = AgentRouterEventService(
        bootstrap_servers=bootstrap_servers,
        consumer_group_id=consumer_group_id,
        registry_path=registry_path,
        health_check_port=health_check_port,
        **db_config,
    )

    # Setup signal handlers for graceful shutdown
    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig}, initiating graceful shutdown...")
        asyncio.create_task(service.stop())

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        # Start service
        await service.start()

        # Run consumer loop
        await service.consume_routing_requests()

    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as e:
        logger.error(f"Service error: {e}", exc_info=True)
    finally:
        await service.stop()


if __name__ == "__main__":
    asyncio.run(main())
