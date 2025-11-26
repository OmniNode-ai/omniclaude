"""
Router Metrics Logger - Async Database Logging System
======================================================

Provides zero-overhead async logging for router cache metrics.

Features:
- Queue-based async writes (non-blocking)
- Batch processing to reduce database load
- Connection pooling for efficiency
- Retry logic with exponential backoff
- Buffer overflow protection
- Graceful shutdown handling

Performance:
- < 1ms overhead per log operation
- Batch writes every 5 seconds or 100 entries
- Max queue size: 10,000 entries
"""

import asyncio
import json
import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from queue import Queue

# Import Pydantic Settings for type-safe configuration
# Type annotation for settings that allows None
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import asyncpg


if TYPE_CHECKING:
    from config import Settings

    settings: Optional["Settings"]

try:
    from config import settings as _settings

    settings = _settings
except ImportError:
    settings = None

# Configure logging
logger = logging.getLogger(__name__)


@dataclass
class CacheMetric:
    """
    Cache metric entry for database logging.

    Attributes:
        query_text: User request text
        cache_hit: Whether cache was hit
        routing_duration_ms: Time to complete routing
        trigger_match_strategy: Strategy used for matching
        confidence_components: JSON breakdown of confidence scoring
        candidates_evaluated: Number of agents evaluated
        timestamp: When metric was recorded
    """

    query_text: str
    cache_hit: bool
    routing_duration_ms: int
    trigger_match_strategy: str
    confidence_components: Dict[str, float]
    candidates_evaluated: int
    timestamp: datetime


class RouterMetricsLogger:
    """
    Async metrics logger with batching and connection pooling.

    Design:
    - Background thread consumes from queue
    - Batches writes for efficiency
    - Handles connection failures gracefully
    - Prevents memory bloat with max queue size
    """

    def __init__(
        self,
        batch_size: int = 100,
        batch_interval_seconds: float = 5.0,
        max_queue_size: int = 10000,
        max_retries: int = 3,
        retry_delay_seconds: float = 1.0,
    ):
        """
        Initialize metrics logger.

        Args:
            batch_size: Max entries per batch write
            batch_interval_seconds: Max time between batch writes
            max_queue_size: Max queue size before blocking
            max_retries: Max retry attempts for failed writes
            retry_delay_seconds: Initial delay between retries
        """
        self.batch_size = batch_size
        self.batch_interval = batch_interval_seconds
        self.max_queue_size = max_queue_size
        self.max_retries = max_retries
        self.retry_delay = retry_delay_seconds

        # Queue for async logging
        self.queue: Queue = Queue(maxsize=max_queue_size)

        # Database connection pool
        self.pool: Optional[asyncpg.Pool] = None

        # Worker thread for batch processing
        self.worker_thread: Optional[threading.Thread] = None
        self.shutdown_event = threading.Event()

        # Statistics - properly typed dict
        self.stats: Dict[str, Any] = {
            "total_logged": 0,
            "total_batches": 0,
            "failed_writes": 0,
            "queue_overflows": 0,
            "last_write_time": None,
        }

        # Thread pool for worker thread (initialized lazily)
        self._thread_pool: Optional[asyncpg.Pool] = None

        # Load database configuration
        self.db_config = self._load_db_config()

    def _load_db_config(self) -> Dict[str, Any]:
        """
        Load database configuration from Pydantic Settings or environment.

        Returns:
            Database configuration dictionary
        """
        # Prefer Pydantic Settings if available (type-safe, validated)
        if settings is not None:
            # Use getattr with fallback for optional attributes
            return {
                "host": settings.postgres_host,
                "port": settings.postgres_port,
                "database": settings.postgres_database,
                "user": settings.postgres_user,
                "password": settings.get_effective_postgres_password(),
                "min_size": settings.postgres_pool_min_size,
                "max_size": settings.postgres_pool_max_size,
                "timeout": getattr(settings, "postgres_query_timeout", 30),
            }

        # Fallback to os.getenv() for backward compatibility
        return {
            "host": os.getenv("POSTGRES_HOST", "192.168.86.200"),
            "port": int(os.getenv("POSTGRES_PORT", 5436)),
            "database": os.getenv("POSTGRES_DATABASE", "omninode_bridge"),
            "user": os.getenv("POSTGRES_USER", "postgres"),
            "password": os.getenv("POSTGRES_PASSWORD", ""),
            "min_size": int(os.getenv("POSTGRES_POOL_MIN_SIZE", 2)),
            "max_size": int(os.getenv("POSTGRES_POOL_MAX_SIZE", 10)),
            "timeout": int(os.getenv("POSTGRES_QUERY_TIMEOUT", 30)),
        }

    async def start(self):
        """
        Start metrics logger with connection pool and worker thread.
        """
        # Create connection pool
        try:
            self.pool = await asyncpg.create_pool(
                host=self.db_config["host"],
                port=self.db_config["port"],
                database=self.db_config["database"],
                user=self.db_config["user"],
                password=self.db_config["password"],
                min_size=self.db_config["min_size"],
                max_size=self.db_config["max_size"],
                command_timeout=self.db_config["timeout"],
            )
            logger.info("Database connection pool created successfully")
        except Exception as e:
            logger.error(f"Failed to create database pool: {e}")
            raise

        # Start worker thread
        self.shutdown_event.clear()
        self.worker_thread = threading.Thread(
            target=self._worker_loop, daemon=True, name="RouterMetricsWorker"
        )
        self.worker_thread.start()
        logger.info("Metrics logger worker thread started")

    async def stop(self):
        """
        Gracefully stop metrics logger and flush remaining entries.
        """
        logger.info("Stopping metrics logger...")

        # Signal shutdown
        self.shutdown_event.set()

        # Wait for worker to finish (it will close its own thread pool)
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=10.0)

        # Close main connection pool
        if self.pool:
            await self.pool.close()
            logger.info("Database connection pool closed")

        logger.info(
            f"Metrics logger stopped. Total logged: {self.stats['total_logged']}"
        )

    def log_cache_metric(
        self,
        query_text: str,
        cache_hit: bool,
        routing_duration_ms: int,
        trigger_match_strategy: str = "unknown",
        confidence_components: Optional[Dict[str, float]] = None,
        candidates_evaluated: int = 0,
    ):
        """
        Log cache metric (non-blocking).

        Args:
            query_text: User request text
            cache_hit: Whether cache was hit
            routing_duration_ms: Routing time in milliseconds
            trigger_match_strategy: Matching strategy used
            confidence_components: Confidence score breakdown
            candidates_evaluated: Number of agents evaluated
        """
        metric = CacheMetric(
            query_text=query_text,
            cache_hit=cache_hit,
            routing_duration_ms=routing_duration_ms,
            trigger_match_strategy=trigger_match_strategy,
            confidence_components=confidence_components or {},
            candidates_evaluated=candidates_evaluated,
            timestamp=datetime.now(timezone.utc),
        )

        try:
            self.queue.put_nowait(metric)
        except Exception:
            # Queue full - increment overflow counter
            self.stats["queue_overflows"] += 1
            logger.warning(
                f"Metrics queue full, dropping entry. Total overflows: {self.stats['queue_overflows']}"
            )

    def _worker_loop(self):
        """
        Worker thread loop for batch processing.

        Runs until shutdown event is set.
        Uses its own event loop to avoid conflicts.
        """
        # Create event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        batch: List[CacheMetric] = []
        last_write = datetime.now(timezone.utc)

        while not self.shutdown_event.is_set():
            try:
                # Check if we should write batch
                time_since_write = (
                    datetime.now(timezone.utc) - last_write
                ).total_seconds()
                should_write = len(batch) >= self.batch_size or (
                    len(batch) > 0 and time_since_write >= self.batch_interval
                )

                if should_write:
                    # Write batch to database using thread's event loop
                    try:
                        loop.run_until_complete(self._write_batch_async(batch, loop))
                        batch.clear()
                        last_write = datetime.now(timezone.utc)
                    except Exception as e:
                        logger.error(f"Failed to write batch: {e}")
                        self.stats["failed_writes"] += len(batch)
                        batch.clear()

                # Get next item with timeout
                try:
                    metric = self.queue.get(timeout=0.5)
                    batch.append(metric)
                except Exception:
                    # Timeout - continue loop
                    pass

            except Exception as e:
                logger.error(f"Error in worker loop: {e}")

        # Final flush on shutdown
        if batch:
            try:
                loop.run_until_complete(self._write_batch_async(batch, loop))
            except Exception as e:
                logger.error(f"Failed to write final batch: {e}")

        # Close thread pool if it exists
        if hasattr(self, "_thread_pool") and self._thread_pool:
            try:
                loop.run_until_complete(self._thread_pool.close())
            except Exception as e:
                logger.debug(f"Error closing thread pool: {e}")

        # Close thread's event loop
        loop.close()

    async def _write_batch_async(
        self, batch: List[CacheMetric], loop: asyncio.AbstractEventLoop
    ):
        """
        Write batch to database with retry logic.

        Args:
            batch: List of cache metrics to write
            loop: Event loop to use for async operations
        """
        if not self.pool:
            logger.error("Database pool not initialized")
            return

        # Create a new pool for this thread if needed
        if not hasattr(self, "_thread_pool") or self._thread_pool is None:
            try:
                self._thread_pool = await asyncpg.create_pool(
                    host=self.db_config["host"],
                    port=self.db_config["port"],
                    database=self.db_config["database"],
                    user=self.db_config["user"],
                    password=self.db_config["password"],
                    min_size=1,
                    max_size=3,
                    command_timeout=self.db_config["timeout"],
                )
            except Exception as e:
                logger.error(f"Failed to create thread pool: {e}")
                return

        for retry in range(self.max_retries):
            try:
                async with self._thread_pool.acquire() as conn:
                    # Prepare batch insert
                    values = [
                        (
                            m.query_text,
                            m.routing_duration_ms,
                            m.cache_hit,
                            m.trigger_match_strategy,
                            json.dumps(m.confidence_components),
                            m.candidates_evaluated,
                        )
                        for m in batch
                    ]

                    # Execute batch insert
                    await conn.executemany(
                        """
                        INSERT INTO router_performance_metrics (
                            query_text,
                            routing_duration_ms,
                            cache_hit,
                            trigger_match_strategy,
                            confidence_components,
                            candidates_evaluated
                        ) VALUES ($1, $2, $3, $4, $5::jsonb, $6)
                        """,
                        values,
                    )

                    # Update stats
                    self.stats["total_logged"] += len(batch)
                    self.stats["total_batches"] += 1
                    self.stats["last_write_time"] = datetime.now(timezone.utc)

                    logger.debug(f"Wrote batch of {len(batch)} metrics to database")
                    return

            except Exception as e:
                if retry < self.max_retries - 1:
                    delay = self.retry_delay * (2**retry)  # Exponential backoff
                    logger.warning(
                        f"Write failed (retry {retry + 1}/{self.max_retries}): {e}"
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        f"Failed to write batch after {self.max_retries} retries: {e}"
                    )
                    self.stats["failed_writes"] += len(batch)

    def get_stats(self) -> Dict[str, Any]:
        """
        Get logger statistics.

        Returns:
            Dictionary with logger performance metrics
        """
        return {
            **self.stats,
            "queue_size": self.queue.qsize(),
            "max_queue_size": self.max_queue_size,
        }


# Singleton instance for global access
_metrics_logger: Optional[RouterMetricsLogger] = None


async def get_metrics_logger() -> RouterMetricsLogger:
    """
    Get or create singleton metrics logger instance.

    Returns:
        Initialized metrics logger
    """
    global _metrics_logger

    if _metrics_logger is None:
        _metrics_logger = RouterMetricsLogger()
        await _metrics_logger.start()

    return _metrics_logger


async def stop_metrics_logger():
    """
    Stop singleton metrics logger instance.
    """
    global _metrics_logger

    if _metrics_logger is not None:
        await _metrics_logger.stop()
        _metrics_logger = None


# Example usage and testing
if __name__ == "__main__":

    async def test_metrics_logger():
        """Test metrics logger functionality."""

        # Load environment variables from .env file
        from pathlib import Path

        env_path = Path(__file__).parent.parent / ".env"

        if env_path.exists():
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        key, value = line.split("=", 1)
                        os.environ[key] = value

        logger = await get_metrics_logger()

        print("Testing metrics logger...")
        print(f"Initial stats: {logger.get_stats()}")

        # Log some test metrics
        test_metrics = [
            ("optimize database", True, 5, "cache_hit", {"total": 0.95}, 0),
            (
                "debug error",
                False,
                45,
                "fuzzy_match",
                {"trigger": 0.8, "context": 0.7},
                5,
            ),
            (
                "create API",
                False,
                52,
                "fuzzy_match",
                {"trigger": 0.85, "context": 0.75},
                4,
            ),
            ("use agent-test", True, 3, "explicit", {"total": 1.0}, 0),
        ]

        for query, hit, duration, strategy, components, candidates in test_metrics:
            logger.log_cache_metric(
                query_text=query,
                cache_hit=hit,
                routing_duration_ms=duration,
                trigger_match_strategy=strategy,
                confidence_components=components,
                candidates_evaluated=candidates,
            )
            print(f"Logged: {query} (hit={hit}, duration={duration}ms)")

        # Wait for batch processing
        print("\nWaiting for batch processing...")
        await asyncio.sleep(6)

        print(f"\nFinal stats: {logger.get_stats()}")

        # Cleanup
        await stop_metrics_logger()
        print("\nMetrics logger stopped")

    # Run test
    asyncio.run(test_metrics_logger())
