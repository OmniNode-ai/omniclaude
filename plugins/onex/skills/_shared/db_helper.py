#!/usr/bin/env python3
"""
Shared Database Helper for Claude Skills
Provides reusable PostgreSQL connection and query utilities.

Note: This module uses structured logging for error reporting.
All errors are logged via Python's logging module with proper severity levels.
"""

import json
import logging
import os
import sys
import uuid
from datetime import UTC, datetime
from typing import Any

import psycopg2
from psycopg2.extensions import connection as psycopg_connection
from psycopg2.extras import RealDictCursor
from psycopg2.pool import SimpleConnectionPool

# Module-level logger for structured logging
logger = logging.getLogger(__name__)


# Add config for type-safe settings (Pydantic Settings framework)
from omniclaude.config import settings

# Database configuration
# Use Pydantic Settings as the single source of truth for OMNICLAUDE_DB_URL.
# The settings object reads from environment variables automatically, so this
# stays consistent with the rest of the codebase rather than diverging via
# a separate os.environ.get() code path.
_omniclaude_db_url = settings.omniclaude_db_url

if _omniclaude_db_url:
    # Parse URL into components for psycopg2 (which doesn't accept DSN URLs directly
    # via SimpleConnectionPool -- we extract components)
    from urllib.parse import urlparse

    _parsed = urlparse(_omniclaude_db_url)
    DB_CONFIG = {
        "host": _parsed.hostname or "",
        "port": _parsed.port or 5432,
        "database": _parsed.path.lstrip("/") if _parsed.path else "",
        "user": _parsed.username or "",
        "password": _parsed.password or "",
    }
else:
    # Fallback to individual POSTGRES_* settings
    DB_CONFIG = {
        "host": settings.postgres_host,
        "port": settings.postgres_port,
        "database": settings.postgres_database,
        "user": settings.postgres_user,
        "password": settings.get_effective_postgres_password(),
    }

# Connection pool (lazy initialization)
_connection_pool: SimpleConnectionPool | None = None


def get_connection_pool() -> SimpleConnectionPool:
    """
    Get or create connection pool.

    Uses fixed pool sizes appropriate for skill helper usage.
    """
    global _connection_pool
    if _connection_pool is None:
        # Hardcoded defaults — pool config fields (postgres_pool_min_size,
        # postgres_pool_max_size) were removed from Settings in DB-SPLIT-07.
        _connection_pool = SimpleConnectionPool(
            minconn=1,
            maxconn=5,
            **DB_CONFIG,
        )
    return _connection_pool


def get_connection() -> psycopg_connection | None:
    """
    Get a database connection from the pool.
    Returns a connection with RealDictCursor for dict-like row access.

    Returns:
        A psycopg2 connection object if successful, None if connection fails.
    """
    try:
        pool = get_connection_pool()
        conn = pool.getconn()
        return conn
    except psycopg2.Error as e:
        # psycopg2.Error: database-level errors (connection, auth, pool exhaustion)
        logger.error(f"Database connection error: {e}")
        return None
    except OSError as e:
        # OSError/IOError: system-level errors (network issues, file descriptors)
        logger.error(f"System error getting database connection: {e}")
        return None


def release_connection(conn: psycopg_connection | None) -> None:
    """
    Release connection back to pool.

    Args:
        conn: The psycopg2 connection to release, or None (which is safely ignored).
    """
    try:
        if conn:
            pool = get_connection_pool()
            pool.putconn(conn)
    except psycopg2.Error as e:
        # psycopg2.Error: database-level errors during connection release
        logger.error(f"Database error releasing connection: {e}")


def execute_query(
    sql: str, params: tuple[Any, ...] | None = None, fetch: bool = True
) -> dict[str, Any]:
    """
    Execute a SQL query safely with parameterized inputs.

    Args:
        sql: SQL query with %s placeholders
        params: Tuple of parameters to substitute
        fetch: If True, return query results (default: True)

    Returns:
        Dict with query results:
        {
            "success": bool,
            "rows": list of dicts (if fetch=True) or None,
            "error": str or None,
            "host": str,
            "port": int,
            "database": str
        }

    Examples:
        >>> # Correct usage - always check success and extract rows
        >>> result = execute_query("SELECT * FROM users WHERE id = %s", (123,))
        >>> if result["success"] and result["rows"]:
        >>>     user = result["rows"][0]
        >>>     print(user["name"])
        >>> else:
        >>>     print(f"Error: {result['error']}")
        >>>
        >>> # For INSERT/UPDATE with RETURNING
        >>> result = execute_query(
        >>>     "INSERT INTO logs (message) VALUES (%s) RETURNING id",
        >>>     ("test message",)
        >>> )
        >>> if result["success"] and result["rows"]:
        >>>     new_id = result["rows"][0]["id"]
        >>>
        >>> # For non-fetch operations
        >>> result = execute_query("UPDATE users SET active = TRUE", fetch=False)
        >>> if result["success"]:
        >>>     print("Update successful")
    """
    conn = None
    try:
        conn = get_connection()
        if not conn:
            return {
                "success": False,
                "rows": None,
                "error": "Failed to get database connection",
                "host": DB_CONFIG.get("host", "unknown"),
                "port": DB_CONFIG.get("port", "unknown"),
                "database": DB_CONFIG.get("database", "unknown"),
            }

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params or ())
            conn.commit()

            rows = cur.fetchall() if fetch else None

            return {
                "success": True,
                "rows": rows,
                "error": None,
                "host": DB_CONFIG.get("host", "unknown"),
                "port": DB_CONFIG.get("port", "unknown"),
                "database": DB_CONFIG.get("database", "unknown"),
            }

    except psycopg2.Error as e:
        # psycopg2.Error: SQL errors, constraint violations, connection issues
        if conn:
            conn.rollback()
        logger.error(f"Database query failed: {e}")
        logger.error(f"SQL: {sql}")
        logger.error(f"Params: {params}")
        return {
            "success": False,
            "rows": None,
            "error": str(e),
            "host": DB_CONFIG.get("host", "unknown"),
            "port": DB_CONFIG.get("port", "unknown"),
            "database": DB_CONFIG.get("database", "unknown"),
        }
    except (TypeError, ValueError) as e:
        # TypeError/ValueError: parameter type mismatches, data conversion errors
        if conn:
            conn.rollback()
        logger.error(f"Query parameter error: {e}")
        logger.error(f"SQL: {sql}")
        logger.error(f"Params: {params}")
        return {
            "success": False,
            "rows": None,
            "error": f"Parameter error: {str(e)}",
            "host": DB_CONFIG.get("host", "unknown"),
            "port": DB_CONFIG.get("port", "unknown"),
            "database": DB_CONFIG.get("database", "unknown"),
        }
    finally:
        if conn:
            release_connection(conn)


def get_correlation_id() -> str:
    """
    Get or generate a correlation ID for tracking related operations.
    Checks environment variable first, then generates new UUID.
    """
    # Try to get from environment (set by hooks)
    corr_id = os.environ.get("CORRELATION_ID")
    if corr_id:
        return corr_id

    # Generate new one
    return str(uuid.uuid4())


def handle_db_error(error: Exception, operation: str) -> dict[str, Any]:
    """
    Handle database errors gracefully and return error info.

    Args:
        error: The exception that occurred
        operation: Description of what operation failed

    Returns:
        Dict with error details
    """
    error_msg = f"{operation} failed: {str(error)}"
    logger.error(error_msg)

    return {
        "success": False,
        "error": str(error),
        "operation": operation,
        "timestamp": datetime.now(UTC).isoformat(),
    }


def test_connection() -> bool:
    """
    Test database connection.
    Returns True if connection successful, False otherwise.
    """
    conn = None
    try:
        conn = get_connection()
        if not conn:
            return False

        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            result = cur.fetchone()

        return result is not None

    except psycopg2.Error as e:
        # psycopg2.Error: database-level errors during connection test
        logger.error(f"Connection test failed (database error): {e}")
        return False
    except OSError as e:
        # OSError/IOError: network issues, system-level errors
        logger.error(f"Connection test failed (system error): {e}")
        return False
    finally:
        if conn:
            release_connection(conn)


def format_timestamp(dt: datetime | None = None) -> str:
    """Format timestamp for database insertion."""
    if dt is None:
        dt = datetime.now(UTC)
    return dt.isoformat()


def parse_json_param(param: str | None) -> dict[str, Any] | None:
    """
    Safely parse JSON parameter from command line.

    Args:
        param: JSON string or None

    Returns:
        Parsed dict or None if param is empty or invalid JSON.
    """
    if not param:
        return None
    try:
        return json.loads(param)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON parameter: {e}")
        return None


if __name__ == "__main__":
    # Test the connection
    print("Testing database connection...")
    if test_connection():
        print("✅ Connection successful!")
        print(f"Correlation ID: {get_correlation_id()}")
    else:
        print("❌ Connection failed!")
        sys.exit(1)
