#!/usr/bin/env python3
"""
Shared Database Helper for Claude Skills
Provides reusable PostgreSQL connection and query utilities.
"""

import json
import os
import sys
import uuid
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from psycopg2.extras import RealDictCursor
from psycopg2.pool import SimpleConnectionPool

# Database configuration
DB_CONFIG = {
    "host": "localhost",
    "port": 5436,
    "database": "omninode_bridge",
    "user": "postgres",
    "password": "omninode-bridge-postgres-dev-2024",
}

# Connection pool (lazy initialization)
_connection_pool: Optional[SimpleConnectionPool] = None


def get_connection_pool() -> SimpleConnectionPool:
    """Get or create connection pool."""
    global _connection_pool
    if _connection_pool is None:
        _connection_pool = SimpleConnectionPool(minconn=1, maxconn=5, **DB_CONFIG)
    return _connection_pool


def get_connection():
    """
    Get a database connection from the pool.
    Returns a connection with RealDictCursor for dict-like row access.
    """
    try:
        pool = get_connection_pool()
        conn = pool.getconn()
        return conn
    except Exception as e:
        print(f"Error getting database connection: {e}", file=sys.stderr)
        return None


def release_connection(conn):
    """Release connection back to pool."""
    try:
        if conn:
            pool = get_connection_pool()
            pool.putconn(conn)
    except Exception as e:
        print(f"Error releasing connection: {e}", file=sys.stderr)


def execute_query(
    sql: str, params: Optional[Tuple] = None, fetch: bool = False
) -> Optional[Any]:
    """
    Execute a SQL query safely with parameterized inputs.

    Args:
        sql: SQL query with %s placeholders
        params: Tuple of parameters to substitute
        fetch: If True, return query results

    Returns:
        Query results if fetch=True, otherwise None
    """
    conn = None
    try:
        conn = get_connection()
        if not conn:
            return None

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params or ())
            conn.commit()

            if fetch:
                return cur.fetchall()
            return True

    except Exception as e:
        if conn:
            conn.rollback()
        print(f"Database query failed: {e}", file=sys.stderr)
        print(f"SQL: {sql}", file=sys.stderr)
        print(f"Params: {params}", file=sys.stderr)
        return None
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


def handle_db_error(error: Exception, operation: str) -> Dict[str, Any]:
    """
    Handle database errors gracefully and return error info.

    Args:
        error: The exception that occurred
        operation: Description of what operation failed

    Returns:
        Dict with error details
    """
    error_msg = f"{operation} failed: {str(error)}"
    print(error_msg, file=sys.stderr)

    return {
        "success": False,
        "error": str(error),
        "operation": operation,
        "timestamp": datetime.utcnow().isoformat(),
    }


def test_connection() -> bool:
    """
    Test database connection.
    Returns True if connection successful, False otherwise.
    """
    try:
        conn = get_connection()
        if not conn:
            return False

        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            result = cur.fetchone()

        release_connection(conn)
        return result is not None

    except Exception as e:
        print(f"Connection test failed: {e}", file=sys.stderr)
        return False


def format_timestamp(dt: Optional[datetime] = None) -> str:
    """Format timestamp for database insertion."""
    if dt is None:
        dt = datetime.utcnow()
    return dt.isoformat()


def parse_json_param(param: Optional[str]) -> Optional[Dict]:
    """
    Safely parse JSON parameter from command line.

    Args:
        param: JSON string or None

    Returns:
        Parsed dict or None
    """
    if not param:
        return None
    try:
        return json.loads(param)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON parameter: {e}", file=sys.stderr)
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
