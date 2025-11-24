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
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


# Configure logging FIRST (before any logging calls)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# Import type-safe configuration
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config import settings


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

# Import required modules (must succeed for service to function)
try:
    from omnibase_core.enums.enum_operation_status import EnumOperationStatus

    from ..lib.agent_execution_logger import log_agent_execution
    from ..lib.agent_router import AgentRouter
    from ..lib.confidence_scoring_publisher import publish_confidence_scored
    from ..lib.data_sanitizer import sanitize_dict, sanitize_string
except ImportError as e:
    logging.error(f"Failed to import required modules: {e}")
    logging.error(f"Python path: {sys.path}")
    raise

# Import ActionLogger separately (optional - graceful degradation if unavailable)
try:
    from ..lib.action_logger import ActionLogger

    ACTION_LOGGER_AVAILABLE = True
except ImportError:
    ACTION_LOGGER_AVAILABLE = False
    logging.warning(
        "ActionLogger not available - enhanced action logging disabled (routing will continue normally)"
    )

# Import Slack notifier for error notifications
try:
    from ..lib.slack_notifier import get_slack_notifier

    SLACK_NOTIFIER_AVAILABLE = True
except ImportError:
    SLACK_NOTIFIER_AVAILABLE = False
    logging.warning("SlackNotifier not available - error notifications disabled")

# Get logger instance (basicConfig already called at module top)
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
        """Initialize database connection pool with retry logic for Docker network timing issues."""
        if self._initialized:
            logger.warning("PostgresLogger already initialized")
            return

        if not ASYNCPG_AVAILABLE:
            logger.error("asyncpg not available - database logging disabled")
            return

        max_retries = 3
        base_delay = 2.0

        for attempt in range(1, max_retries + 1):
            try:
                logger.info(
                    f"Initializing PostgreSQL connection pool (attempt {attempt}/{max_retries}, "
                    f"host: {self.host}:{self.port}, db: {self.database})"
                )

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
                return

            except (ConnectionRefusedError, asyncio.TimeoutError, OSError) as e:
                if attempt < max_retries:
                    delay = base_delay * (2 ** (attempt - 1))
                    logger.warning(
                        f"PostgreSQL pool initialization failed (attempt {attempt}/{max_retries}): {e}. "
                        f"Retrying in {delay}s... (Docker network may still be initializing)"
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        f"Failed to initialize PostgreSQL pool after {max_retries} attempts: {e}",
                        exc_info=True,
                    )
                    self._initialized = False

                    # Send Slack notification for database connection failure
                    if SLACK_NOTIFIER_AVAILABLE:
                        try:
                            notifier = get_slack_notifier()

                            asyncio.create_task(
                                notifier.send_error_notification(
                                    error=e,
                                    context={
                                        "service": "agent_router_event_service",
                                        "operation": "postgres_initialization",
                                        "db_host": self.host,
                                        "db_port": self.port,
                                        "db_name": self.database,
                                        "attempts": max_retries,
                                    },
                                )
                            )
                        except Exception as notify_error:
                            logger.debug(
                                f"Failed to send Slack notification: {notify_error}"
                            )

            except Exception as e:
                # Non-connection errors (auth, config, etc.) - fail immediately
                logger.error(
                    f"Failed to initialize PostgreSQL pool (non-retryable error): {e}",
                    exc_info=True,
                )
                self._initialized = False

                # Send Slack notification for database connection failure
                if SLACK_NOTIFIER_AVAILABLE:
                    try:
                        notifier = get_slack_notifier()

                        asyncio.create_task(
                            notifier.send_error_notification(
                                error=e,
                                context={
                                    "service": "agent_router_event_service",
                                    "operation": "postgres_initialization",
                                    "db_host": self.host,
                                    "db_port": self.port,
                                    "db_name": self.database,
                                    "error_type": "non_retryable",
                                },
                            )
                        )
                    except Exception as notify_error:
                        logger.debug(
                            f"Failed to send Slack notification: {notify_error}"
                        )

                return  # Exit retry loop on non-retryable errors

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

    async def log_performance_metrics(
        self,
        metric_type: str,
        selected_agent: str,
        selection_strategy: str,
        confidence_score: float,
        alternatives_count: int,
        total_routing_time_us: int,
        cache_lookup_us: int,
        trigger_matching_us: int,
        confidence_scoring_us: int,
        cache_hit: bool,
        trigger_confidence: float,
        context_confidence: float,
        capability_confidence: float,
        historical_confidence: float,
        correlation_id: Optional[str] = None,
        user_request_hash: Optional[str] = None,
        context_hash: Optional[str] = None,
        alternative_agents: Optional[List[Dict[str, Any]]] = None,
        max_retries: int = 3,
    ) -> Optional[str]:
        """
        Log router performance metrics to database with retry logic.

        Non-blocking - will not raise exceptions even if logging fails.

        Args:
            metric_type: Type of metric (e.g., 'routing_decision')
            selected_agent: Agent selected by router
            selection_strategy: Strategy used for routing
            confidence_score: Overall confidence score (0.0-1.0)
            alternatives_count: Number of alternative recommendations
            total_routing_time_us: Total routing time in microseconds
            cache_lookup_us: Cache lookup time in microseconds
            trigger_matching_us: Trigger matching time in microseconds
            confidence_scoring_us: Confidence scoring time in microseconds
            cache_hit: Whether cache was hit
            trigger_confidence: Trigger component of confidence (0.0-1.0)
            context_confidence: Context component of confidence (0.0-1.0)
            capability_confidence: Capability component of confidence (0.0-1.0)
            historical_confidence: Historical component of confidence (0.0-1.0)
            correlation_id: Correlation ID for traceability
            user_request_hash: Hash of user request
            context_hash: Hash of context
            alternative_agents: Alternative recommendations (JSONB)
            max_retries: Maximum retry attempts (default: 3)

        Returns:
            Record ID on success, None on failure
        """
        if not self._initialized or not self._pool:
            logger.debug(
                "PostgresLogger not initialized - skipping performance metrics log"
            )
            return None

        # Prepare data
        alternative_agents_json = json.dumps(alternative_agents or [])

        insert_sql = """
            INSERT INTO router_performance_metrics (
                metric_type,
                correlation_id,
                user_request_hash,
                context_hash,
                selected_agent,
                selection_strategy,
                confidence_score,
                alternative_agents,
                alternatives_count,
                cache_lookup_us,
                trigger_matching_us,
                confidence_scoring_us,
                total_routing_time_us,
                trigger_confidence,
                context_confidence,
                capability_confidence,
                historical_confidence,
                cache_hit,
                measured_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19)
            RETURNING id
        """

        # Retry loop with exponential backoff
        retry_delay = 0.1

        for attempt in range(max_retries):
            try:
                async with self._pool.acquire() as conn:
                    record_id = await conn.fetchval(
                        insert_sql,
                        metric_type,
                        correlation_id,
                        user_request_hash,
                        context_hash,
                        selected_agent,
                        selection_strategy,
                        confidence_score,
                        alternative_agents_json,
                        alternatives_count,
                        cache_lookup_us,
                        trigger_matching_us,
                        confidence_scoring_us,
                        total_routing_time_us,
                        trigger_confidence,
                        context_confidence,
                        capability_confidence,
                        historical_confidence,
                        cache_hit,
                        datetime.now(UTC),
                    )

                    logger.debug(
                        f"Performance metrics logged (record_id: {record_id}, agent: {selected_agent}, total_time_us: {total_routing_time_us})"
                    )
                    return str(record_id)

            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(
                        f"Performance metrics logging failed (attempt {attempt + 1}/{max_retries}), retrying in {retry_delay}s: {e}"
                    )
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    logger.error(
                        f"Performance metrics logging failed after {max_retries} attempts: {e}",
                        exc_info=True,
                    )

        return None


class AgentRouterEventService:
    """
    Kafka consumer service for agent routing events.

    Consumes routing requests from Kafka, processes using AgentRouter,
    publishes responses, and logs decisions to PostgreSQL.
    """

    # Kafka topic names
    TOPIC_REQUEST = "omninode.agent.routing.requested.v1"
    TOPIC_COMPLETED = "omninode.agent.routing.completed.v1"
    TOPIC_FAILED = "omninode.agent.routing.failed.v1"

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
        # Priority: 1) explicit parameter, 2) REGISTRY_PATH env var, 3) home directory default
        if registry_path is None:
            registry_path = os.getenv("REGISTRY_PATH")
            if registry_path is None:
                registry_path = str(
                    Path.home()
                    / ".claude"
                    / "agent-definitions"
                    / "agent-registry.yaml"
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
            auto_offset_reset="earliest",
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
            # Security: Binding to 0.0.0.0 is intentional for Docker/Kubernetes deployments
            # For production, use firewall rules or reverse proxy for access control
            site = web.TCPSite(
                self._health_runner,
                "0.0.0.0",  # nosec B104 # noqa: S104
                self.health_check_port,
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

        # CRITICAL: Validate correlation_id BEFORE ActionLogger initialization
        # This prevents invalid state and silent failures
        if not correlation_id:
            self.logger.error("Missing correlation_id in routing request")
            # Publish failure event
            if self._producer:
                error_envelope = {
                    "correlation_id": "unknown",
                    "event_type": "omninode.agent.routing.failed.v1",
                    "payload": {
                        "error_code": "VALIDATION_ERROR",
                        "error_message": "Missing correlation_id in routing request",
                        "routing_time_ms": 0,
                    },
                    "timestamp": datetime.now(UTC).isoformat(),
                }
                try:
                    await self._producer.send_and_wait(
                        self.TOPIC_FAILED, error_envelope
                    )
                except Exception as publish_error:
                    self.logger.error(f"Failed to publish error event: {publish_error}")
            return

        # Validate UUID format
        try:
            uuid.UUID(correlation_id)
        except ValueError:
            self.logger.error(f"Invalid correlation_id format: {correlation_id}")
            # Publish failure event
            if self._producer:
                error_envelope = {
                    "correlation_id": correlation_id,
                    "event_type": "omninode.agent.routing.failed.v1",
                    "payload": {
                        "error_code": "VALIDATION_ERROR",
                        "error_message": f"Invalid correlation_id format (not a valid UUID): {correlation_id}",
                        "routing_time_ms": 0,
                    },
                    "timestamp": datetime.now(UTC).isoformat(),
                }
                try:
                    await self._producer.send_and_wait(
                        self.TOPIC_FAILED, error_envelope
                    )
                except Exception as publish_error:
                    self.logger.error(f"Failed to publish error event: {publish_error}")
            return

        # NOW safe to initialize ActionLogger with validated correlation_id
        action_logger = None
        if ACTION_LOGGER_AVAILABLE:
            try:
                action_logger = ActionLogger(
                    agent_name="agent-router-service",
                    correlation_id=correlation_id,  # Now validated!
                    project_name="omniclaude",
                    project_path=str(Path(__file__).parent.parent.parent),
                    working_directory=os.getcwd(),
                    debug_mode=True,
                )
            except Exception as e:
                # Non-blocking - log error but continue routing
                self.logger.warning(f"Failed to initialize ActionLogger: {e}")

        # Initialize execution logger for lifecycle tracking
        execution_logger = None
        try:
            execution_logger = await log_agent_execution(
                agent_name="agent-router-service",
                user_prompt=user_request,
                correlation_id=correlation_id,
            )
        except Exception as e:
            # Non-blocking - log error but continue routing
            self.logger.warning(f"Failed to initialize execution logger: {e}")

        try:
            # Extract routing options
            max_recommendations = options.get("max_recommendations", 5)

            # Log progress: starting routing analysis (non-blocking)
            if execution_logger:
                try:
                    asyncio.create_task(
                        execution_logger.progress(
                            stage="routing_analysis",
                            percent=25,
                            metadata={"max_recommendations": max_recommendations},
                        )
                    )
                except Exception as e:
                    self.logger.debug(f"Progress logging failed: {e}")

            # Route using AgentRouter
            if not self._router:
                raise RuntimeError("AgentRouter not initialized")

            recommendations = self._router.route(
                user_request=user_request,
                context=context,
                max_recommendations=max_recommendations,
            )

            routing_time_ms = (time.time() - start_time) * 1000

            # Log progress: routing completed (non-blocking)
            if execution_logger:
                try:
                    asyncio.create_task(
                        execution_logger.progress(
                            stage="routing_completed",
                            percent=75,
                            metadata={"routing_time_ms": routing_time_ms},
                        )
                    )
                except Exception as e:
                    self.logger.debug(f"Progress logging failed: {e}")

            # Handle no recommendations (fallback)
            if not recommendations:
                self.logger.warning(
                    f"No recommendations for request (correlation_id: {correlation_id})"
                )
                recommendations = [self._create_fallback_recommendation()]

            # Primary recommendation
            primary = recommendations[0]

            # Log routing decision with ActionLogger
            if action_logger:
                try:
                    await action_logger.log_decision(
                        decision_name="agent_routing",
                        decision_context=sanitize_dict(
                            {
                                "user_request": sanitize_string(
                                    user_request, max_length=200
                                ),  # Sanitize and truncate
                                "max_recommendations": max_recommendations,
                                "candidates_evaluated": len(recommendations),
                            }
                        ),
                        decision_result=sanitize_dict(
                            {
                                "selected_agent": primary.agent_name,
                                "confidence": primary.confidence.total,
                                "reasoning": primary.reason,
                                "alternatives": [
                                    {
                                        "agent_name": rec.agent_name,
                                        "confidence": rec.confidence.total,
                                    }
                                    for rec in recommendations[
                                        1:3
                                    ]  # Top 2 alternatives
                                ],
                            }
                        ),
                        duration_ms=int(routing_time_ms),
                    )
                    self.logger.debug(
                        f"ActionLogger: Decision logged (agent: {primary.agent_name}, confidence: {primary.confidence.total:.2%})"
                    )
                except Exception as e:
                    # Non-blocking - log error but don't fail routing
                    self.logger.debug(f"ActionLogger decision logging failed: {e}")

            # Log routing as tool_call for performance tracking
            if action_logger:
                try:
                    await action_logger.log_tool_call(
                        tool_name="AgentRouter",
                        tool_parameters=sanitize_dict(
                            {
                                "user_request": sanitize_string(
                                    user_request, max_length=200
                                ),  # Sanitize and truncate
                                "max_recommendations": max_recommendations,
                            }
                        ),
                        tool_result=sanitize_dict(
                            {
                                "selected_agent": primary.agent_name,
                                "confidence": primary.confidence.total,
                                "recommendation_count": len(recommendations),
                            }
                        ),
                        duration_ms=int(routing_time_ms),
                        success=True,
                    )
                    self.logger.debug(
                        f"ActionLogger: Tool call logged (routing_time: {routing_time_ms:.1f}ms)"
                    )
                except Exception as e:
                    # Non-blocking - log error but don't fail routing
                    self.logger.debug(f"ActionLogger tool call logging failed: {e}")

            # Build response envelope (using EVENT_BUS_INTEGRATION_GUIDE standard format)
            response_envelope = {
                "correlation_id": correlation_id,
                "event_type": "omninode.agent.routing.completed.v1",
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

            # Publish completed event with error handling
            if self._producer:
                try:
                    future = await self._producer.send_and_wait(
                        self.TOPIC_COMPLETED, response_envelope
                    )
                    self.logger.debug(
                        f"Routing completed event published successfully (correlation_id: {correlation_id})"
                    )
                except Exception as e:
                    self.logger.error(
                        f"Failed to publish routing completed event (correlation_id: {correlation_id}): {e}",
                        exc_info=True,
                    )
                    # Don't re-raise - routing succeeded, only event publishing failed

            # Publish confidence scoring event (non-blocking)
            try:
                asyncio.create_task(
                    publish_confidence_scored(
                        agent_name=primary.agent_name,
                        confidence_score=primary.confidence.total,
                        routing_strategy="enhanced_fuzzy_matching",  # TODO: Get from router
                        correlation_id=correlation_id,
                        factors={
                            "trigger_score": primary.confidence.trigger_score,
                            "context_score": primary.confidence.context_score,
                            "capability_score": primary.confidence.capability_score,
                            "historical_score": primary.confidence.historical_score,
                        },
                    )
                )
                self.logger.debug(
                    f"Confidence scoring event queued for async publishing (agent: {primary.agent_name}, score: {primary.confidence.total:.2%})"
                )
            except Exception as e:
                # Non-blocking - log error but don't fail routing
                self.logger.warning(
                    f"Failed to queue confidence scoring event: {e}", exc_info=True
                )

            # Log to database (non-blocking - fire-and-forget)
            if self._postgres_logger:
                asyncio.create_task(
                    self._postgres_logger.log_routing_decision(
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
                )

                # Log performance metrics if timing data is available (non-blocking)
                if self._router and self._router.last_routing_timing:
                    timing = self._router.last_routing_timing
                    try:
                        asyncio.create_task(
                            self._postgres_logger.log_performance_metrics(
                                metric_type="routing_decision",
                                selected_agent=primary.agent_name,
                                selection_strategy="enhanced_fuzzy_matching",
                                confidence_score=primary.confidence.total,
                                alternatives_count=len(recommendations) - 1,
                                total_routing_time_us=timing.total_routing_time_us,
                                cache_lookup_us=timing.cache_lookup_us,
                                trigger_matching_us=timing.trigger_matching_us,
                                confidence_scoring_us=timing.confidence_scoring_us,
                                cache_hit=timing.cache_hit,
                                trigger_confidence=primary.confidence.trigger_score,
                                context_confidence=primary.confidence.context_score,
                                capability_confidence=primary.confidence.capability_score,
                                historical_confidence=primary.confidence.historical_score,
                                correlation_id=correlation_id,
                                alternative_agents=[
                                    {
                                        "agent_name": rec.agent_name,
                                        "confidence": rec.confidence.total,
                                        "reason": rec.reason,
                                    }
                                    for rec in recommendations[1:]
                                ],
                            )
                        )
                        self.logger.debug(
                            f"Performance metrics queued for async logging (total_time_us: {timing.total_routing_time_us}, cache_hit: {timing.cache_hit})"
                        )
                    except Exception as e:
                        # Non-blocking - log error but don't fail routing
                        self.logger.warning(
                            f"Failed to queue performance metrics: {e}", exc_info=True
                        )

            self._requests_succeeded += 1
            self.logger.info(
                f"Routing completed (correlation_id: {correlation_id}, agent: {primary.agent_name}, confidence: {primary.confidence.total:.2%}, time: {routing_time_ms:.1f}ms)"
            )

            # Log execution completion: success (non-blocking)
            if execution_logger:
                try:
                    asyncio.create_task(
                        execution_logger.complete(
                            status=EnumOperationStatus.SUCCESS,
                            quality_score=primary.confidence.total,
                            metadata={
                                "selected_agent": primary.agent_name,
                                "confidence": primary.confidence.total,
                                "routing_time_ms": routing_time_ms,
                                "recommendation_count": len(recommendations),
                            },
                        )
                    )
                except Exception as e:
                    self.logger.warning(f"Execution completion logging failed: {e}")

        except Exception as e:
            self._requests_failed += 1
            routing_time_ms = (time.time() - start_time) * 1000

            self.logger.error(
                f"Routing failed (correlation_id: {correlation_id}): {e}",
                exc_info=True,
            )

            # Log error with ActionLogger
            if action_logger:
                try:
                    await action_logger.log_error(
                        error_type=type(e).__name__,
                        error_message=str(e),
                        error_context=sanitize_dict(
                            {
                                "user_request": sanitize_string(
                                    user_request, max_length=200
                                ),  # Sanitize and truncate
                                "routing_time_ms": routing_time_ms,
                                "max_recommendations": options.get(
                                    "max_recommendations", 5
                                ),
                            }
                        ),
                        severity="error",
                        send_slack_notification=False,  # Already handled by SlackNotifier below
                    )
                    self.logger.debug(
                        f"ActionLogger: Error logged (type: {type(e).__name__})"
                    )
                except Exception as action_log_error:
                    # Non-blocking - log error but don't fail routing
                    self.logger.debug(
                        f"ActionLogger error logging failed: {action_log_error}"
                    )

            # Send Slack notification for routing failure
            if SLACK_NOTIFIER_AVAILABLE:
                try:
                    notifier = get_slack_notifier()
                    asyncio.create_task(
                        notifier.send_error_notification(
                            error=e,
                            context={
                                "service": "agent_router_event_service",
                                "operation": "routing_execution",
                                "correlation_id": correlation_id,
                                "user_request": user_request[:200],
                                "routing_time_ms": routing_time_ms,
                            },
                        )
                    )
                except Exception as notify_error:
                    self.logger.debug(
                        f"Failed to send Slack notification: {notify_error}"
                    )

            # Publish failed event (using EVENT_BUS_INTEGRATION_GUIDE standard format)
            if self._producer:
                error_envelope = {
                    "correlation_id": correlation_id,
                    "event_type": "omninode.agent.routing.failed.v1",
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

            # Log execution completion: failure (non-blocking)
            if execution_logger:
                try:
                    asyncio.create_task(
                        execution_logger.complete(
                            status=EnumOperationStatus.FAILED,
                            error_message=str(e),
                            error_type=type(e).__name__,
                            metadata={
                                "routing_time_ms": routing_time_ms,
                            },
                        )
                    )
                except Exception as log_error:
                    self.logger.warning(
                        f"Execution completion logging failed: {log_error}"
                    )

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
    # Load configuration from type-safe settings
    bootstrap_servers = settings.kafka_bootstrap_servers
    consumer_group_id = settings.kafka_group_id
    registry_path = os.getenv("REGISTRY_PATH")  # Optional override
    health_check_port = settings.health_check_port

    # PostgreSQL configuration
    db_config = {
        "db_host": settings.postgres_host,
        "db_port": settings.postgres_port,
        "db_name": settings.postgres_database,
        "db_user": settings.postgres_user,
        "db_password": settings.get_effective_postgres_password(),
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
