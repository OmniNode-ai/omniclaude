import os
import asyncio
from typing import Optional

import asyncpg

try:
    # Load variables from .env if present
    from dotenv import load_dotenv  # type: ignore

    load_dotenv()
except Exception:
    pass


_pool: Optional[asyncpg.Pool] = None


def _build_dsn_from_env() -> Optional[str]:
    host = os.getenv("POSTGRES_HOST")
    port = os.getenv("POSTGRES_PORT")
    db = os.getenv("POSTGRES_DATABASE") or os.getenv("POSTGRES_DB") or os.getenv("POSTGRES_DBNAME")
    user = os.getenv("POSTGRES_USER")
    password = os.getenv("POSTGRES_PASSWORD")
    if not host or not port or not db or not user:
        return None
    pw = f":{password}" if password else ""
    return f"postgresql://{user}{pw}@{host}:{port}/{db}"


async def get_pg_pool() -> Optional[asyncpg.Pool]:
    """Create or return a shared asyncpg pool based on PG_DSN or POSTGRES_* envs.

    If connection info is not set, returns None and callers should noop.
    """
    global _pool
    if _pool is not None:
        return _pool

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


