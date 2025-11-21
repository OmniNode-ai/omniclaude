"""
PostgreSQL Logger for Routing Decisions.

Logs all routing decisions to the agent_routing_decisions table for audit trail
and analytics. Follows ONEX v2.0 patterns with non-blocking error handling.

Features:
    - Async connection pooling with asyncpg
    - Non-blocking logging (doesn't fail routing on DB error)
    - Retry logic with exponential backoff
    - Graceful degradation on failures
    - Connection pool health monitoring

Implementation: Phase 2 - Event-Driven Routing Analytics
"""

import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional
from uuid import UUID


try:
    import asyncpg
    from asyncpg import Pool

    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False
    asyncpg = None  # type: ignore
    Pool = Any  # type: ignore

logger = logging.getLogger(__name__)


class PostgresLogger:
    """
    PostgreSQL logger for routing decisions.

    Provides non-blocking asynchronous logging of routing decisions to the
    agent_routing_decisions table with automatic retry and graceful degradation.
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
        """
        Initialize PostgreSQL logger.

        Args:
            host: PostgreSQL host address
            port: PostgreSQL port
            database: Database name
            user: Database user
            password: Database password
            pool_min_size: Minimum connection pool size (default: 2)
            pool_max_size: Maximum connection pool size (default: 10)
        """
        if not ASYNCPG_AVAILABLE:
            raise RuntimeError(
                "asyncpg is not available. Install with: pip install asyncpg"
            )

        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.pool_min_size = pool_min_size
        self.pool_max_size = pool_max_size

        self._pool: Optional[Pool] = None
        self._initialized = False
        self._connection_string = (
            f"postgresql://{user}:***@{host}:{port}/{database}"  # Sanitized for logs
        )

        # Metrics
        self._log_count = 0
        self._success_count = 0
        self._error_count = 0
        self._retry_count = 0
        self._total_log_time_ms = 0.0

    async def initialize(self) -> None:
        """
        Initialize database connection pool.

        Raises:
            RuntimeError: If connection pool initialization fails
        """
        if self._initialized:
            logger.warning("PostgresLogger already initialized")
            return

        logger.info(
            "Initializing PostgreSQL connection pool",
            extra={
                "host": self.host,
                "port": self.port,
                "database": self.database,
                "pool_min_size": self.pool_min_size,
                "pool_max_size": self.pool_max_size,
            },
        )

        try:
            # Create connection pool
            self._pool = await asyncpg.create_pool(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password,
                min_size=self.pool_min_size,
                max_size=self.pool_max_size,
                command_timeout=10.0,  # 10 second timeout for commands
                timeout=5.0,  # 5 second timeout for acquiring connection
            )

            # Test connection
            async with self._pool.acquire() as conn:
                await conn.fetchval("SELECT 1")

            self._initialized = True
            logger.info(
                "PostgreSQL connection pool initialized successfully",
                extra={
                    "pool_size": self._pool.get_size(),
                    "pool_free": self._pool.get_idle_size(),
                },
            )

        except Exception as e:
            logger.error(
                f"Failed to initialize PostgreSQL connection pool: {e}", exc_info=True
            )
            raise RuntimeError(f"PostgreSQL pool initialization failed: {e}") from e

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
        context: Optional[Dict[str, Any]] = None,
        project_path: Optional[str] = None,
        project_name: Optional[str] = None,
        claude_session_id: Optional[str] = None,
        max_retries: int = 3,
    ) -> Optional[UUID]:
        """
        Log routing decision to database with retry logic.

        This method is non-blocking and will not raise exceptions even if logging
        fails. Failures are logged as warnings/errors but do not affect routing.

        Args:
            user_request: The user's request text
            selected_agent: Selected agent name
            confidence_score: Confidence score (0.0-1.0)
            routing_strategy: Strategy used for routing
            routing_time_ms: Time taken for routing in milliseconds
            correlation_id: Correlation ID for traceability (optional)
            alternatives: Alternative agent recommendations (optional)
            reasoning: Reasoning for selection (optional)
            context: Additional context (optional)
            project_path: Project path (optional)
            project_name: Project name (optional)
            claude_session_id: Claude session ID (optional)
            max_retries: Maximum retry attempts (default: 3)

        Returns:
            UUID of inserted record on success, None on failure
        """
        if not self._initialized:
            logger.error(
                "PostgresLogger not initialized. Call initialize() first.",
                extra={"selected_agent": selected_agent},
            )
            return None

        # Track metrics
        self._log_count += 1
        start_time = time.perf_counter()

        # Prepare data
        alternatives_json = json.dumps(alternatives or [])
        context_json = json.dumps(context or {})
        routing_time_int = int(round(routing_time_ms))

        # SQL INSERT statement
        insert_sql = """
            INSERT INTO agent_routing_decisions (
                correlation_id,
                user_request,
                selected_agent,
                confidence_score,
                alternatives,
                reasoning,
                routing_strategy,
                context,
                routing_time_ms,
                project_path,
                project_name,
                claude_session_id,
                created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            RETURNING id
        """

        # Retry loop with exponential backoff
        retry_delay = 0.1  # Start with 100ms delay

        for attempt in range(max_retries):
            try:
                async with self._pool.acquire() as conn:
                    # Execute INSERT and get returned UUID
                    record_id = await conn.fetchval(
                        insert_sql,
                        correlation_id,
                        user_request,
                        selected_agent,
                        confidence_score,
                        alternatives_json,
                        reasoning,
                        routing_strategy,
                        context_json,
                        routing_time_int,
                        project_path,
                        project_name,
                        claude_session_id,
                        datetime.now(UTC),
                    )

                    # Success!
                    self._success_count += 1
                    elapsed_ms = (time.perf_counter() - start_time) * 1000
                    self._total_log_time_ms += elapsed_ms

                    logger.info(
                        "Routing decision logged successfully",
                        extra={
                            "record_id": str(record_id),
                            "selected_agent": selected_agent,
                            "confidence_score": confidence_score,
                            "routing_time_ms": routing_time_int,
                            "log_time_ms": round(elapsed_ms, 2),
                            "attempt": attempt + 1,
                        },
                    )

                    return record_id

            except asyncpg.PostgresError as e:
                self._retry_count += 1

                if attempt < max_retries - 1:
                    # Retry with exponential backoff
                    logger.warning(
                        f"Routing decision logging failed (attempt {attempt + 1}/{max_retries}), retrying in {retry_delay}s: {e}",
                        extra={
                            "selected_agent": selected_agent,
                            "error_type": type(e).__name__,
                            "retry_delay_s": retry_delay,
                        },
                    )
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    # Final attempt failed
                    self._error_count += 1
                    logger.error(
                        f"Routing decision logging failed after {max_retries} attempts: {e}",
                        extra={
                            "selected_agent": selected_agent,
                            "confidence_score": confidence_score,
                            "error_type": type(e).__name__,
                        },
                        exc_info=True,
                    )

            except Exception as e:
                # Unexpected error - log and return None
                self._error_count += 1
                logger.error(
                    f"Unexpected error logging routing decision: {e}",
                    extra={
                        "selected_agent": selected_agent,
                        "error_type": type(e).__name__,
                    },
                    exc_info=True,
                )
                break  # Don't retry on unexpected errors

        # All retries failed
        return None

    async def health_check(self) -> Dict[str, Any]:
        """
        Perform health check on database connection.

        Returns:
            Health check result with status and metrics
        """
        if not self._initialized:
            return {
                "status": "unhealthy",
                "error": "Not initialized",
                "timestamp": datetime.now(UTC).isoformat(),
            }

        try:
            start_time = time.perf_counter()

            # Test connection with simple query
            async with self._pool.acquire() as conn:
                _ = await conn.fetchval("SELECT 1")

            elapsed_ms = (time.perf_counter() - start_time) * 1000

            return {
                "status": "healthy",
                "timestamp": datetime.now(UTC).isoformat(),
                "pool_size": self._pool.get_size(),
                "pool_free": self._pool.get_idle_size(),
                "test_query_ms": round(elapsed_ms, 2),
                "metrics": self.get_metrics(),
            }

        except Exception as e:
            logger.error(f"Health check failed: {e}", exc_info=True)
            return {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.now(UTC).isoformat(),
            }

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get logging metrics.

        Returns:
            Dictionary of metrics:
            - log_count: Total log attempts
            - success_count: Successful logs
            - error_count: Failed logs
            - retry_count: Total retries
            - success_rate: Success percentage
            - avg_log_time_ms: Average log time
        """
        success_rate = (
            (self._success_count / self._log_count * 100)
            if self._log_count > 0
            else 0.0
        )

        avg_log_time_ms = (
            (self._total_log_time_ms / self._success_count)
            if self._success_count > 0
            else 0.0
        )

        return {
            "log_count": self._log_count,
            "success_count": self._success_count,
            "error_count": self._error_count,
            "retry_count": self._retry_count,
            "success_rate": round(success_rate, 2),
            "avg_log_time_ms": round(avg_log_time_ms, 2),
        }

    async def shutdown(self) -> None:
        """Shutdown connection pool and cleanup resources."""
        if not self._initialized:
            return

        logger.info(
            "Shutting down PostgreSQL logger",
            extra={"final_metrics": self.get_metrics()},
        )

        if self._pool:
            await self._pool.close()
            self._pool = None

        self._initialized = False
