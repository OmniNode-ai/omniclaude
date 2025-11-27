import os
from typing import Any

import asyncpg


try:
    # Load variables from .env if present
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

# Import Pydantic Settings for type-safe configuration
try:
    from config import settings

    SETTINGS_AVAILABLE = True
except ImportError:
    SETTINGS_AVAILABLE = False


_pool: asyncpg.Pool | None = None


def _build_dsn_from_env() -> str | None:
    """Build PostgreSQL DSN from environment variables or Pydantic Settings."""
    # Prefer Pydantic Settings if available (type-safe, validated)
    if SETTINGS_AVAILABLE:
        try:
            # Use Pydantic Settings helper method for DSN generation
            return settings.get_postgres_dsn()
        except Exception:
            pass  # Fall through to os.getenv

    # Fallback to os.getenv() for backward compatibility
    host = os.getenv("POSTGRES_HOST")
    port = os.getenv("POSTGRES_PORT")
    db = (
        os.getenv("POSTGRES_DATABASE")
        or os.getenv("POSTGRES_DB")
        or os.getenv("POSTGRES_DBNAME")
    )
    user = os.getenv("POSTGRES_USER")
    password = os.getenv("POSTGRES_PASSWORD")
    if not host or not port or not db or not user:
        return None
    pw = f":{password}" if password else ""
    return f"postgresql://{user}{pw}@{host}:{port}/{db}"


async def get_pg_pool() -> asyncpg.Pool | None:
    """Create or return a shared asyncpg pool based on PG_DSN or POSTGRES_* envs.

    If connection info is not set, returns None and callers should noop.
    """
    global _pool
    if _pool is not None:
        return _pool

    # Try PG_DSN from environment first, then build from individual vars
    dsn = os.getenv("PG_DSN") or _build_dsn_from_env()
    if not dsn:
        return None

    _pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=5)
    return _pool


async def close_pg_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def execute_query(query: str, *args) -> Any:
    """Execute a query and return results.

    Helper function for agent framework schema operations.

    Args:
        query: SQL query string
        *args: Query parameters

    Returns:
        Query results
    """
    pool = await get_pg_pool()
    if pool is None:
        return None

    async with pool.acquire() as conn:
        return await conn.fetch(query, *args)


async def execute_command(query: str, *args) -> str:
    """Execute a command (INSERT, UPDATE, DELETE) and return status.

    Helper function for agent framework schema operations.

    Args:
        query: SQL command string
        *args: Command parameters

    Returns:
        Command status string
    """
    pool = await get_pg_pool()
    if pool is None:
        return ""

    async with pool.acquire() as conn:
        result = await conn.execute(query, *args)
        return str(result) if result else ""
