"""Database connection utilities with connection pooling."""

import os

# Add config for type-safe settings
import sys
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from psycopg2 import pool
from psycopg2.extras import RealDictCursor

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config import settings


class DatabasePool:
    """Singleton database connection pool manager."""

    _instance: Optional["DatabasePool"] = None
    _pool: pool.SimpleConnectionPool | None = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize database connection pool."""
        if self._pool is None:
            self._pool = pool.SimpleConnectionPool(
                minconn=1,
                maxconn=10,
                host=os.getenv("POSTGRES_HOST", "localhost"),
                port=int(os.getenv("POSTGRES_PORT", "5436")),
                database=os.getenv("POSTGRES_DATABASE", "omninode_bridge"),
                user=os.getenv("POSTGRES_USER", "postgres"),
                password=settings.get_effective_postgres_password(),
            )

    @contextmanager
    def get_connection(self) -> Generator:
        """Get a connection from the pool.

        Yields:
            psycopg2.connection: Database connection

        Example:
            with db_pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM table")
        """
        conn = self._pool.getconn()
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            self._pool.putconn(conn)

    def close_all(self):
        """Close all connections in the pool."""
        if self._pool:
            self._pool.closeall()


# Global database pool instance
db_pool = DatabasePool()


@contextmanager
def get_db_cursor(dict_cursor: bool = True) -> Generator:
    """Get a database cursor from the connection pool.

    Args:
        dict_cursor: If True, use RealDictCursor for dict-like results

    Yields:
        psycopg2.cursor: Database cursor

    Example:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT * FROM table")
            results = cursor.fetchall()
    """
    with db_pool.get_connection() as conn:
        cursor_factory = RealDictCursor if dict_cursor else None
        cursor = conn.cursor(cursor_factory=cursor_factory)
        try:
            yield cursor
        finally:
            cursor.close()


def test_connection() -> bool:
    """Test database connection.

    Returns:
        bool: True if connection successful, False otherwise
    """
    try:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT 1")
            return True
    except Exception:
        return False


def execute_query(query: str, params: tuple | None = None, fetch: bool = True):
    """Execute a database query.

    Args:
        query: SQL query to execute
        params: Query parameters
        fetch: If True, fetch and return results

    Returns:
        Query results if fetch=True, None otherwise

    Raises:
        psycopg2.Error: Database error
    """
    with get_db_cursor() as cursor:
        cursor.execute(query, params)
        if fetch:
            return cursor.fetchall()
        return None
