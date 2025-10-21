"""
Database Integration Layer for Agent Observability Framework

Provides unified database access for all observability components with:
- Async connection pooling with asyncpg
- Batch write operations for high-volume logging (1000+ events/second)
- Query API for observability data retrieval
- Data retention and archival policies
- Health monitoring and auto-recovery
- Circuit breaker pattern for failure handling
- Graceful degradation if database unavailable

DEPENDENCY: Requires Stream 1 database schema to be deployed first.
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import asyncpg
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class DatabaseHealthStatus(str, Enum):
    """Database health status states."""

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
    RECOVERING = "RECOVERING"


class CircuitState(str, Enum):
    """Circuit breaker states."""

    CLOSED = "CLOSED"  # Normal operation
    OPEN = "OPEN"  # Failing, reject requests
    HALF_OPEN = "HALF_OPEN"  # Testing recovery


class DatabaseConfig(BaseModel):
    """Database configuration from environment."""

    host: str = "localhost"
    port: int = 5436
    database: str = "omninode_bridge"
    user: str = "postgres"
    password: str = ""  # Set via environment variable

    # Connection pool settings
    pool_min_size: int = 5
    pool_max_size: int = 20
    pool_exhaustion_threshold: float = 80.0  # Percentage
    max_queries_per_connection: int = 10000
    connection_max_age: int = 3600  # Seconds
    query_timeout: int = 30  # Seconds
    acquire_timeout: int = 10  # Seconds

    # Batch write settings
    batch_size: int = 100
    batch_timeout_ms: int = 1000
    max_batch_queue_size: int = 10000

    # Circuit breaker settings
    failure_threshold: int = 5
    recovery_timeout: int = 60
    half_open_attempts: int = 3

    # Retention policy settings
    trace_events_retention_days: int = 30
    routing_decisions_retention_days: int = 90
    performance_metrics_retention_days: int = 180
    transformation_events_retention_days: int = 90

    @classmethod
    def from_env(cls) -> "DatabaseConfig":
        """Load configuration from environment variables."""
        import os

        return cls(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=int(os.getenv("POSTGRES_PORT", "5436")),
            database=os.getenv("POSTGRES_DATABASE", "omninode_bridge"),
            user=os.getenv("POSTGRES_USER", "postgres"),
            password=os.getenv("POSTGRES_PASSWORD", ""),  # Must be set via environment
            pool_min_size=int(os.getenv("POSTGRES_POOL_MIN_SIZE", "5")),
            pool_max_size=int(os.getenv("POSTGRES_POOL_MAX_SIZE", "20")),
            pool_exhaustion_threshold=float(
                os.getenv("POSTGRES_POOL_EXHAUSTION_THRESHOLD", "80.0")
            ),
            max_queries_per_connection=int(
                os.getenv("POSTGRES_MAX_QUERIES_PER_CONNECTION", "10000")
            ),
            connection_max_age=int(os.getenv("POSTGRES_CONNECTION_MAX_AGE", "3600")),
            query_timeout=int(os.getenv("POSTGRES_QUERY_TIMEOUT", "30")),
            acquire_timeout=int(os.getenv("POSTGRES_ACQUIRE_TIMEOUT", "10")),
        )


class DatabaseHealthMetrics(BaseModel):
    """Database health and performance metrics."""

    status: DatabaseHealthStatus
    pool_size: int
    pool_free: int
    pool_utilization_pct: float
    total_queries: int = 0
    failed_queries: int = 0
    avg_query_time_ms: float = 0.0
    circuit_state: CircuitState
    last_error: Optional[str] = None
    last_error_time: Optional[datetime] = None
    recovery_attempts: int = 0
    uptime_seconds: float = 0.0


class BatchWriteBuffer:
    """Buffer for batching write operations."""

    def __init__(self, max_size: int = 100, timeout_ms: int = 1000):
        self.max_size = max_size
        self.timeout_ms = timeout_ms
        self.buffer: List[Tuple[str, List[Any]]] = []
        self.lock = asyncio.Lock()
        self.flush_event = asyncio.Event()
        self.last_flush = time.time()

    async def add(self, query: str, params: List[Any]) -> bool:
        """Add query to buffer. Returns True if buffer should be flushed."""
        async with self.lock:
            self.buffer.append((query, params))

            # Check if we should flush
            should_flush = (
                len(self.buffer) >= self.max_size
                or (time.time() - self.last_flush) * 1000 >= self.timeout_ms
            )

            if should_flush:
                self.flush_event.set()

            return should_flush

    async def get_batch(self) -> List[Tuple[str, List[Any]]]:
        """Get current batch and clear buffer."""
        async with self.lock:
            batch = self.buffer.copy()
            self.buffer.clear()
            self.last_flush = time.time()
            self.flush_event.clear()
            return batch


class CircuitBreaker:
    """Circuit breaker for database failure handling."""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        half_open_attempts: int = 3,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_attempts = half_open_attempts

        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time: Optional[float] = None
        self.half_open_successes = 0
        self.lock = asyncio.Lock()

    async def call(self, func, *args, **kwargs):
        """Execute function through circuit breaker."""
        async with self.lock:
            # Check if circuit is open
            if self.state == CircuitState.OPEN:
                # Check if recovery timeout has elapsed
                if (
                    self.last_failure_time
                    and time.time() - self.last_failure_time >= self.recovery_timeout
                ):
                    logger.info(
                        "Circuit breaker entering HALF_OPEN state for recovery test"
                    )
                    self.state = CircuitState.HALF_OPEN
                    self.half_open_successes = 0
                else:
                    raise Exception("Circuit breaker is OPEN - database unavailable")

        # Try to execute function
        try:
            result = await func(*args, **kwargs)

            # Handle success based on state
            async with self.lock:
                if self.state == CircuitState.HALF_OPEN:
                    self.half_open_successes += 1
                    if self.half_open_successes >= self.half_open_attempts:
                        logger.info("Circuit breaker closing - recovery successful")
                        self.state = CircuitState.CLOSED
                        self.failure_count = 0
                        self.last_failure_time = None
                elif self.state == CircuitState.CLOSED:
                    # Reset failure count on success
                    self.failure_count = 0

            return result

        except Exception:
            # Handle failure
            async with self.lock:
                self.failure_count += 1
                self.last_failure_time = time.time()

                if self.state == CircuitState.HALF_OPEN:
                    logger.warning("Circuit breaker re-opening - recovery failed")
                    self.state = CircuitState.OPEN
                elif (
                    self.state == CircuitState.CLOSED
                    and self.failure_count >= self.failure_threshold
                ):
                    logger.error(
                        f"Circuit breaker opening - failure threshold reached ({self.failure_count} failures)"
                    )
                    self.state = CircuitState.OPEN

            raise


class DatabaseIntegrationLayer:
    """
    Unified database integration layer for agent observability.

    Features:
    - Async connection pooling with health monitoring
    - Batch write operations (1000+ events/second target)
    - Query API for observability data retrieval
    - Data retention and archival policies
    - Circuit breaker for failure handling
    - Graceful degradation if database unavailable

    Usage:
        config = DatabaseConfig.from_env()
        db = DatabaseIntegrationLayer(config)
        await db.initialize()

        # Batch write
        await db.write_trace_event(trace_data)

        # Query
        events = await db.query_trace_events(trace_id="coord_123")

        # Cleanup
        await db.shutdown()
    """

    def __init__(self, config: Optional[DatabaseConfig] = None):
        self.config = config or DatabaseConfig.from_env()
        self.pool: Optional[asyncpg.Pool] = None
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=self.config.failure_threshold,
            recovery_timeout=self.config.recovery_timeout,
            half_open_attempts=self.config.half_open_attempts,
        )

        # Batch write buffers
        self.trace_event_buffer = BatchWriteBuffer(
            max_size=self.config.batch_size, timeout_ms=self.config.batch_timeout_ms
        )
        self.routing_decision_buffer = BatchWriteBuffer(
            max_size=self.config.batch_size, timeout_ms=self.config.batch_timeout_ms
        )
        self.performance_metrics_buffer = BatchWriteBuffer(
            max_size=self.config.batch_size, timeout_ms=self.config.batch_timeout_ms
        )
        self.transformation_event_buffer = BatchWriteBuffer(
            max_size=self.config.batch_size, timeout_ms=self.config.batch_timeout_ms
        )

        # Health monitoring
        self.start_time = time.time()
        self.total_queries = 0
        self.failed_queries = 0
        self.query_times: List[float] = []
        self.last_error: Optional[str] = None
        self.last_error_time: Optional[datetime] = None

        # Background tasks
        self.flush_task: Optional[asyncio.Task] = None
        self.health_check_task: Optional[asyncio.Task] = None
        self.retention_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()

        logger.info(
            f"DatabaseIntegrationLayer initialized with config: {self.config.model_dump()}"
        )

    async def initialize(self) -> bool:
        """
        Initialize database connection pool and start background tasks.

        Returns:
            bool: True if initialization successful, False otherwise
        """
        try:
            logger.info("Initializing database connection pool...")

            # Create connection pool
            self.pool = await asyncpg.create_pool(
                host=self.config.host,
                port=self.config.port,
                database=self.config.database,
                user=self.config.user,
                password=self.config.password,
                min_size=self.config.pool_min_size,
                max_size=self.config.pool_max_size,
                command_timeout=self.config.query_timeout,
                max_queries=self.config.max_queries_per_connection,
                max_inactive_connection_lifetime=self.config.connection_max_age,
            )

            # Test connection
            async with self.pool.acquire() as conn:
                version = await conn.fetchval("SELECT version()")
                logger.info(f"Database connection established: {version}")

            # Start background tasks
            self.flush_task = asyncio.create_task(self._flush_loop())
            self.health_check_task = asyncio.create_task(self._health_check_loop())
            self.retention_task = asyncio.create_task(self._retention_loop())

            logger.info("Database integration layer initialized successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            self.last_error = str(e)
            self.last_error_time = datetime.now()
            return False

    async def shutdown(self):
        """Shutdown database connections and background tasks."""
        logger.info("Shutting down database integration layer...")

        # Signal shutdown
        self._shutdown_event.set()

        # Flush remaining data
        await self._flush_all_buffers()

        # Cancel background tasks
        if self.flush_task:
            self.flush_task.cancel()
        if self.health_check_task:
            self.health_check_task.cancel()
        if self.retention_task:
            self.retention_task.cancel()

        # Close pool
        if self.pool:
            await self.pool.close()
            logger.info("Database connection pool closed")

    @asynccontextmanager
    async def acquire(self):
        """Acquire database connection from pool with circuit breaker."""
        if not self.pool:
            raise Exception("Database pool not initialized")

        async def _acquire():
            return await self.pool.acquire(timeout=self.config.acquire_timeout)

        conn = await self.circuit_breaker.call(_acquire)
        try:
            yield conn
        finally:
            await self.pool.release(conn)

    async def execute_query(self, query: str, *params, fetch: str = "none") -> Any:
        """
        Execute query with circuit breaker and performance tracking.

        Args:
            query: SQL query string
            params: Query parameters
            fetch: "none", "one", "all", or "val"

        Returns:
            Query result based on fetch mode
        """
        start_time = time.time()

        try:

            async def _execute():
                async with self.acquire() as conn:
                    if fetch == "all":
                        return await conn.fetch(query, *params)
                    elif fetch == "one":
                        return await conn.fetchrow(query, *params)
                    elif fetch == "val":
                        return await conn.fetchval(query, *params)
                    else:
                        return await conn.execute(query, *params)

            result = await self.circuit_breaker.call(_execute)

            # Track metrics
            query_time = (time.time() - start_time) * 1000
            self.total_queries += 1
            self.query_times.append(query_time)

            # Keep only last 1000 query times for avg calculation
            if len(self.query_times) > 1000:
                self.query_times = self.query_times[-1000:]

            return result

        except Exception as e:
            self.failed_queries += 1
            self.last_error = str(e)
            self.last_error_time = datetime.now()
            logger.error(f"Query failed: {e}")
            raise

    # =========================================================================
    # BATCH WRITE OPERATIONS
    # =========================================================================

    async def write_trace_event(
        self,
        trace_id: str,
        event_type: str,
        level: str,
        message: str,
        metadata: Optional[Dict[str, Any]] = None,
        agent_name: Optional[str] = None,
        task_id: Optional[str] = None,
        duration_ms: Optional[float] = None,
    ):
        """
        Write trace event to buffer for batch insertion.

        NOTE: This method assumes Stream 1 schema exists.
        If schema doesn't exist, events will be buffered but insertion will fail gracefully.
        """
        query = """
            INSERT INTO agent_observability.trace_events
            (trace_id, event_type, level, message, metadata, agent_name, task_id, duration_ms)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """

        import json

        params = [
            trace_id,
            event_type,
            level,
            message,
            json.dumps(metadata or {}),
            agent_name,
            task_id,
            duration_ms,
        ]

        await self.trace_event_buffer.add(query, params)

    async def write_routing_decision(
        self,
        user_request: str,
        selected_agent: str,
        confidence_score: float,
        alternatives: List[Dict[str, Any]],
        reasoning: str,
        routing_strategy: str = "enhanced",
        context: Optional[Dict[str, Any]] = None,
        routing_time_ms: Optional[float] = None,
    ):
        """Write routing decision to buffer for batch insertion."""
        query = """
            INSERT INTO agent_observability.routing_decisions
            (user_request, selected_agent, confidence_score, alternatives, reasoning,
             routing_strategy, context, routing_time_ms)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """

        import json

        params = [
            user_request,
            selected_agent,
            confidence_score,
            json.dumps(alternatives),
            reasoning,
            routing_strategy,
            json.dumps(context or {}),
            routing_time_ms,
        ]

        await self.routing_decision_buffer.add(query, params)

    async def write_performance_metric(
        self,
        metric_name: str,
        metric_value: float,
        metric_type: str,
        component: str,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Write performance metric to buffer for batch insertion."""
        query = """
            INSERT INTO agent_observability.performance_metrics
            (metric_name, metric_value, metric_type, component, metadata)
            VALUES ($1, $2, $3, $4, $5)
        """

        import json

        params = [
            metric_name,
            metric_value,
            metric_type,
            component,
            json.dumps(metadata or {}),
        ]

        await self.performance_metrics_buffer.add(query, params)

    async def write_transformation_event(
        self,
        source_agent: str,
        target_agent: str,
        transformation_reason: str,
        capabilities_inherited: List[str],
        transformation_context: Optional[Dict[str, Any]] = None,
        transformation_time_ms: Optional[float] = None,
    ):
        """Write agent transformation event to buffer for batch insertion."""
        query = """
            INSERT INTO agent_observability.transformation_events
            (source_agent, target_agent, transformation_reason, capabilities_inherited,
             transformation_context, transformation_time_ms)
            VALUES ($1, $2, $3, $4, $5, $6)
        """

        import json

        params = [
            source_agent,
            target_agent,
            transformation_reason,
            json.dumps(capabilities_inherited),
            json.dumps(transformation_context or {}),
            transformation_time_ms,
        ]

        await self.transformation_event_buffer.add(query, params)

    async def _flush_buffer(self, buffer: BatchWriteBuffer, buffer_name: str):
        """Flush a specific buffer to database."""
        batch = await buffer.get_batch()

        if not batch:
            return

        try:
            async with self.acquire() as conn:
                async with conn.transaction():
                    for query, params in batch:
                        await conn.execute(query, *params)

            logger.debug(f"Flushed {len(batch)} {buffer_name} records to database")

        except Exception as e:
            logger.error(f"Failed to flush {buffer_name} buffer: {e}")
            # Note: In production, you might want to retry or write to fallback storage

    async def _flush_all_buffers(self):
        """Flush all buffers to database."""
        await asyncio.gather(
            self._flush_buffer(self.trace_event_buffer, "trace_event"),
            self._flush_buffer(self.routing_decision_buffer, "routing_decision"),
            self._flush_buffer(self.performance_metrics_buffer, "performance_metrics"),
            self._flush_buffer(
                self.transformation_event_buffer, "transformation_event"
            ),
            return_exceptions=True,
        )

    async def _flush_loop(self):
        """Background task to flush buffers periodically."""
        logger.info("Starting batch flush loop")

        while not self._shutdown_event.is_set():
            try:
                # Wait for flush event or timeout
                await asyncio.wait_for(
                    asyncio.gather(
                        self.trace_event_buffer.flush_event.wait(),
                        self.routing_decision_buffer.flush_event.wait(),
                        self.performance_metrics_buffer.flush_event.wait(),
                        self.transformation_event_buffer.flush_event.wait(),
                    ),
                    timeout=self.config.batch_timeout_ms / 1000,
                )
            except asyncio.TimeoutError:
                pass

            # Flush all buffers
            await self._flush_all_buffers()

            await asyncio.sleep(0.1)  # Small delay to prevent tight loop

    # =========================================================================
    # QUERY API
    # =========================================================================

    async def query_trace_events(
        self,
        trace_id: Optional[str] = None,
        agent_name: Optional[str] = None,
        event_type: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query trace events with filters."""
        conditions = []
        params = []
        param_count = 1

        if trace_id:
            conditions.append(f"trace_id = ${param_count}")
            params.append(trace_id)
            param_count += 1

        if agent_name:
            conditions.append(f"agent_name = ${param_count}")
            params.append(agent_name)
            param_count += 1

        if event_type:
            conditions.append(f"event_type = ${param_count}")
            params.append(event_type)
            param_count += 1

        if start_time:
            conditions.append(f"created_at >= ${param_count}")
            params.append(start_time)
            param_count += 1

        if end_time:
            conditions.append(f"created_at <= ${param_count}")
            params.append(end_time)
            param_count += 1

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

        query = f"""
            SELECT * FROM agent_observability.trace_events
            {where_clause}
            ORDER BY created_at DESC
            LIMIT ${param_count}
        """
        params.append(limit)

        try:
            rows = await self.execute_query(query, *params, fetch="all")
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to query trace events: {e}")
            return []

    async def query_routing_decisions(
        self,
        selected_agent: Optional[str] = None,
        min_confidence: Optional[float] = None,
        routing_strategy: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query routing decisions with filters."""
        conditions = []
        params = []
        param_count = 1

        if selected_agent:
            conditions.append(f"selected_agent = ${param_count}")
            params.append(selected_agent)
            param_count += 1

        if min_confidence is not None:
            conditions.append(f"confidence_score >= ${param_count}")
            params.append(min_confidence)
            param_count += 1

        if routing_strategy:
            conditions.append(f"routing_strategy = ${param_count}")
            params.append(routing_strategy)
            param_count += 1

        if start_time:
            conditions.append(f"created_at >= ${param_count}")
            params.append(start_time)
            param_count += 1

        if end_time:
            conditions.append(f"created_at <= ${param_count}")
            params.append(end_time)
            param_count += 1

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

        query = f"""
            SELECT * FROM agent_observability.routing_decisions
            {where_clause}
            ORDER BY created_at DESC
            LIMIT ${param_count}
        """
        params.append(limit)

        try:
            rows = await self.execute_query(query, *params, fetch="all")
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to query routing decisions: {e}")
            return []

    # =========================================================================
    # HEALTH MONITORING
    # =========================================================================

    async def get_health_metrics(self) -> DatabaseHealthMetrics:
        """Get current database health metrics."""
        if not self.pool:
            return DatabaseHealthMetrics(
                status=DatabaseHealthStatus.UNHEALTHY,
                pool_size=0,
                pool_free=0,
                pool_utilization_pct=0.0,
                circuit_state=self.circuit_breaker.state,
                last_error=self.last_error,
                last_error_time=self.last_error_time,
                uptime_seconds=time.time() - self.start_time,
            )

        pool_size = self.pool.get_size()
        pool_free = self.pool.get_idle_size()
        pool_utilization = (
            ((pool_size - pool_free) / pool_size * 100) if pool_size > 0 else 0.0
        )

        avg_query_time = (
            sum(self.query_times) / len(self.query_times) if self.query_times else 0.0
        )

        # Determine health status
        if self.circuit_breaker.state == CircuitState.OPEN:
            status = DatabaseHealthStatus.UNHEALTHY
        elif self.circuit_breaker.state == CircuitState.HALF_OPEN:
            status = DatabaseHealthStatus.RECOVERING
        elif pool_utilization >= self.config.pool_exhaustion_threshold:
            status = DatabaseHealthStatus.DEGRADED
        else:
            status = DatabaseHealthStatus.HEALTHY

        return DatabaseHealthMetrics(
            status=status,
            pool_size=pool_size,
            pool_free=pool_free,
            pool_utilization_pct=pool_utilization,
            total_queries=self.total_queries,
            failed_queries=self.failed_queries,
            avg_query_time_ms=avg_query_time,
            circuit_state=self.circuit_breaker.state,
            last_error=self.last_error,
            last_error_time=self.last_error_time,
            recovery_attempts=self.circuit_breaker.half_open_successes,
            uptime_seconds=time.time() - self.start_time,
        )

    async def _health_check_loop(self):
        """Background task for health monitoring."""
        logger.info("Starting health check loop")

        while not self._shutdown_event.is_set():
            try:
                metrics = await self.get_health_metrics()

                # Log health status
                if metrics.status == DatabaseHealthStatus.UNHEALTHY:
                    logger.error(
                        f"Database health: {metrics.status.value} - Circuit: {metrics.circuit_state.value}"
                    )
                elif metrics.status == DatabaseHealthStatus.DEGRADED:
                    logger.warning(
                        f"Database health: {metrics.status.value} - "
                        f"Pool utilization: {metrics.pool_utilization_pct:.1f}%"
                    )
                else:
                    logger.debug(
                        f"Database health: {metrics.status.value} - "
                        f"Queries: {metrics.total_queries} ({metrics.failed_queries} failed), "
                        f"Avg query time: {metrics.avg_query_time_ms:.2f}ms"
                    )

                # Alert on high pool utilization
                if (
                    metrics.pool_utilization_pct
                    >= self.config.pool_exhaustion_threshold
                ):
                    logger.warning(
                        f"Connection pool utilization high: {metrics.pool_utilization_pct:.1f}% "
                        f"({metrics.pool_size - metrics.pool_free}/{metrics.pool_size} connections in use)"
                    )

            except Exception as e:
                logger.error(f"Health check failed: {e}")

            await asyncio.sleep(60)  # Check every minute

    # =========================================================================
    # DATA RETENTION AND ARCHIVAL
    # =========================================================================

    async def apply_retention_policy(self):
        """Apply data retention policies to observability tables."""
        logger.info("Applying data retention policies...")

        try:
            # Archive and delete old trace events
            cutoff_date = datetime.now() - timedelta(
                days=self.config.trace_events_retention_days
            )
            deleted = await self.execute_query(
                """
                DELETE FROM agent_observability.trace_events
                WHERE created_at < $1
                """,
                cutoff_date,
                fetch="val",
            )
            logger.info(
                f"Deleted {deleted} trace events older than {self.config.trace_events_retention_days} days"
            )

            # Archive and delete old routing decisions
            cutoff_date = datetime.now() - timedelta(
                days=self.config.routing_decisions_retention_days
            )
            deleted = await self.execute_query(
                """
                DELETE FROM agent_observability.routing_decisions
                WHERE created_at < $1
                """,
                cutoff_date,
                fetch="val",
            )
            logger.info(
                f"Deleted {deleted} routing decisions older than {self.config.routing_decisions_retention_days} days"
            )

            # Archive and delete old performance metrics
            cutoff_date = datetime.now() - timedelta(
                days=self.config.performance_metrics_retention_days
            )
            deleted = await self.execute_query(
                """
                DELETE FROM agent_observability.performance_metrics
                WHERE created_at < $1
                """,
                cutoff_date,
                fetch="val",
            )
            logger.info(
                f"Deleted {deleted} performance metrics older than {self.config.performance_metrics_retention_days} days"
            )

            # Archive and delete old transformation events
            cutoff_date = datetime.now() - timedelta(
                days=self.config.transformation_events_retention_days
            )
            deleted = await self.execute_query(
                """
                DELETE FROM agent_observability.transformation_events
                WHERE created_at < $1
                """,
                cutoff_date,
                fetch="val",
            )
            logger.info(
                f"Deleted {deleted} transformation events older than {self.config.transformation_events_retention_days} days"
            )

            logger.info("Retention policy applied successfully")

        except Exception as e:
            logger.error(f"Failed to apply retention policy: {e}")

    async def _retention_loop(self):
        """Background task for data retention enforcement."""
        logger.info("Starting retention policy loop")

        while not self._shutdown_event.is_set():
            try:
                await self.apply_retention_policy()
            except Exception as e:
                logger.error(f"Retention policy task failed: {e}")

            # Run retention policy daily
            await asyncio.sleep(86400)


# =========================================================================
# GLOBAL INSTANCE
# =========================================================================

_database_layer: Optional[DatabaseIntegrationLayer] = None


def get_database_layer() -> DatabaseIntegrationLayer:
    """Get or create global database integration layer instance."""
    global _database_layer
    if _database_layer is None:
        _database_layer = DatabaseIntegrationLayer()
    return _database_layer


async def initialize_database_layer() -> bool:
    """Initialize global database layer."""
    layer = get_database_layer()
    return await layer.initialize()


async def shutdown_database_layer():
    """Shutdown global database layer."""
    global _database_layer
    if _database_layer:
        await _database_layer.shutdown()
        _database_layer = None
