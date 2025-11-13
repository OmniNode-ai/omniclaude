"""
Database Connection Pool Configuration - ONEX Effect Node Pattern
Author: agent-workflow-coordinator
Created: 2025-10-09

ONEX Compliance:
- Effect node: Manages external database I/O
- Naming: NodeDatabasePoolEffect pattern
- Lifecycle: Proper initialization and cleanup
- Error handling: OnexError with exception chaining

Performance Targets:
- Connection acquisition: <50ms
- Pool initialization: <300ms
- Health check: <100ms
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncGenerator, Optional

import asyncpg
from asyncpg.pool import Pool

# Import Pydantic Settings for type-safe configuration
try:
    from config import settings
except ImportError:
    settings = None

logger = logging.getLogger(__name__)


@dataclass
class DatabaseConfig:
    """Database connection configuration."""

    host: str = "192.168.86.200"  # Production default (matches Pydantic settings)
    port: int = 5436
    database: str = "omninode_bridge"
    user: str = "postgres"
    password: str = ""  # Set via environment variable

    # Pool configuration
    min_size: int = 5
    max_size: int = 20
    max_queries: int = 50000
    max_inactive_connection_lifetime: float = 300.0  # 5 minutes
    timeout: float = 60.0  # Connection timeout
    command_timeout: float = 60.0  # Command timeout

    @classmethod
    def from_env(cls) -> "DatabaseConfig":
        """
        Load database configuration from environment variables.

        Reads standard POSTGRES_* environment variables to construct a DatabaseConfig
        instance with production defaults for missing values. Prefers Pydantic Settings
        defaults when available for type safety.

        Returns:
            DatabaseConfig: Configuration loaded from environment with defaults

        Example:
            >>> config = DatabaseConfig.from_env()
            >>> print(config.host)
            '192.168.86.200'
        """
        # Prefer Pydantic Settings defaults if available (type-safe)
        if settings:
            default_host = settings.postgres_host
            default_port = settings.postgres_port
            default_database = settings.postgres_database
            default_user = settings.postgres_user
        else:
            # Fallback to hardcoded defaults for backward compatibility
            default_host = "192.168.86.200"
            default_port = 5436
            default_database = "omninode_bridge"
            default_user = "postgres"

        # Note: Uses standard POSTGRES_* environment variables
        return cls(
            host=os.getenv("POSTGRES_HOST", default_host),
            port=int(os.getenv("POSTGRES_PORT", str(default_port))),
            database=os.getenv("POSTGRES_DATABASE", default_database),
            user=os.getenv("POSTGRES_USER", default_user),
            password=os.getenv("POSTGRES_PASSWORD", ""),  # Must be set via environment
        )

    def get_dsn(self) -> str:
        """Get database connection DSN."""
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"


class NodeDatabasePoolEffect:
    """
    ONEX Effect Node: Database connection pool manager.

    Responsibilities:
    - Initialize and manage asyncpg connection pool
    - Provide connection acquisition interface
    - Monitor pool health and performance
    - Proper lifecycle management (init/cleanup)

    ONEX Pattern: Effect (External I/O - Database)
    """

    def __init__(self, config: Optional[DatabaseConfig] = None):
        """
        Initialize database pool effect node.

        Args:
            config: Database configuration. If None, loads from environment.
        """
        self.config = config or DatabaseConfig.from_env()
        self._pool: Optional[Pool] = None
        self._initialized = False

    async def initialize(self) -> None:
        """
        Initialize connection pool.

        Performance target: <300ms

        Raises:
            OnexError: If pool initialization fails
        """
        if self._initialized:
            logger.warning("Database pool already initialized")
            return

        try:
            logger.info(
                f"Initializing database pool: {self.config.host}:{self.config.port}/{self.config.database}"
            )

            self._pool = await asyncpg.create_pool(
                host=self.config.host,
                port=self.config.port,
                database=self.config.database,
                user=self.config.user,
                password=self.config.password,
                min_size=self.config.min_size,
                max_size=self.config.max_size,
                max_queries=self.config.max_queries,
                max_inactive_connection_lifetime=self.config.max_inactive_connection_lifetime,
                timeout=self.config.timeout,
                command_timeout=self.config.command_timeout,
            )

            self._initialized = True
            logger.info(
                f"Database pool initialized: min={self.config.min_size}, max={self.config.max_size}"
            )

            # Verify connection
            await self.health_check()

        except Exception as e:
            logger.error(f"Failed to initialize database pool: {e}")
            raise RuntimeError(f"Database pool initialization failed: {e}") from e

    async def cleanup(self) -> None:
        """
        Cleanup connection pool.

        Performance target: <150ms
        """
        if not self._initialized or self._pool is None:
            return

        try:
            logger.info("Closing database pool...")
            await self._pool.close()
            self._pool = None
            self._initialized = False
            logger.info("Database pool closed successfully")

        except Exception as e:
            logger.error(f"Error closing database pool: {e}")
            raise RuntimeError(f"Database pool cleanup failed: {e}") from e

    @asynccontextmanager
    async def acquire(self) -> AsyncGenerator[asyncpg.Connection, None]:
        """
        Acquire connection from pool.

        Performance target: <50ms

        Yields:
            Database connection from pool

        Raises:
            RuntimeError: If pool not initialized
            OnexError: If connection acquisition fails

        Example:
            async with pool.acquire() as conn:
                result = await conn.fetchrow("SELECT * FROM agent_definitions")
        """
        if not self._initialized or self._pool is None:
            raise RuntimeError(
                "Database pool not initialized. Call initialize() first."
            )

        conn = None
        try:
            conn = await self._pool.acquire()
            yield conn
        except Exception as e:
            logger.error(f"Error acquiring database connection: {e}")
            raise RuntimeError(f"Database connection acquisition failed: {e}") from e
        finally:
            if conn is not None:
                try:
                    await self._pool.release(conn)
                except Exception as e:
                    logger.error(f"Error releasing database connection: {e}")

    async def health_check(self) -> bool:
        """
        Perform database health check.

        Performance target: <100ms

        Returns:
            True if database is healthy, False otherwise
        """
        try:
            async with self.acquire() as conn:
                result = await conn.fetchval("SELECT 1")
                return result == 1

        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False

    def get_pool_stats(self) -> dict:
        """
        Get connection pool statistics.

        Returns:
            Dictionary with pool statistics
        """
        if not self._initialized or self._pool is None:
            return {
                "initialized": False,
                "size": 0,
                "free": 0,
            }

        return {
            "initialized": True,
            "size": self._pool.get_size(),
            "free": self._pool.get_idle_size(),
            "min_size": self._pool.get_min_size(),
            "max_size": self._pool.get_max_size(),
        }

    async def execute_migration(self, migration_file: str) -> bool:
        """
        Execute SQL migration file.

        Args:
            migration_file: Path to SQL migration file

        Returns:
            True if migration successful, False otherwise
        """
        try:
            with open(migration_file, "r") as f:
                sql = f.read()

            async with self.acquire() as conn:
                async with conn.transaction():
                    await conn.execute(sql)

            logger.info(f"Migration executed successfully: {migration_file}")
            return True

        except Exception as e:
            logger.error(f"Migration failed: {migration_file}: {e}")
            return False


# Global pool instance
_global_pool: Optional[NodeDatabasePoolEffect] = None


async def get_database_pool() -> NodeDatabasePoolEffect:
    """
    Get global database pool instance.

    Returns:
        Initialized database pool

    Raises:
        RuntimeError: If pool initialization fails
    """
    global _global_pool

    if _global_pool is None:
        _global_pool = NodeDatabasePoolEffect()
        await _global_pool.initialize()

    return _global_pool


async def cleanup_database_pool() -> None:
    """Cleanup global database pool."""
    global _global_pool

    if _global_pool is not None:
        await _global_pool.cleanup()
        _global_pool = None


# Context manager for pool lifecycle
@asynccontextmanager
async def database_pool_context(
    config: Optional[DatabaseConfig] = None,
) -> AsyncGenerator[NodeDatabasePoolEffect, None]:
    """
    Context manager for database pool lifecycle.

    Args:
        config: Optional database configuration

    Yields:
        Initialized database pool

    Example:
        async with database_pool_context() as pool:
            async with pool.acquire() as conn:
                result = await conn.fetchrow("SELECT * FROM agent_definitions")
    """
    pool = NodeDatabasePoolEffect(config)
    try:
        await pool.initialize()
        yield pool
    finally:
        await pool.cleanup()


if __name__ == "__main__":
    # Test database connection
    async def test_connection():
        """Test database connection and pool."""
        print("Testing database connection pool...")

        async with database_pool_context() as pool:
            print(f"Pool stats: {pool.get_pool_stats()}")

            # Health check
            is_healthy = await pool.health_check()
            print(f"Health check: {'✓ PASS' if is_healthy else '✗ FAIL'}")

            # Test query
            async with pool.acquire() as conn:
                version = await conn.fetchval("SELECT version()")
                print(f"Database version: {version}")

            print(f"Final pool stats: {pool.get_pool_stats()}")

    asyncio.run(test_connection())
