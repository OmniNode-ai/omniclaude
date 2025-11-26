"""
Database Migration Script

Setup:
    Run from project root with proper PYTHONPATH:

        cd /path/to/omniclaude
        PYTHONPATH=/path/to/omniclaude python agents/lib/migrate.py

    Or install the package in development mode:

        pip install -e .
"""

import asyncio
from pathlib import Path
from typing import List

from agents.lib.db import get_pg_pool


async def _ensure_migrations_table(conn) -> str:
    # Create table if missing
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (applied_at TIMESTAMPTZ DEFAULT NOW())"
    )

    # Determine identifier column to use (support existing schemas)
    for col in ("filename", "name", "id", "version"):
        exists = await conn.fetchval(
            "SELECT 1 FROM information_schema.columns WHERE table_name='schema_migrations' AND column_name=$1",
            col,
        )
        if exists:
            return col
    # Fallback to a synthetic column we can add for tracking if none exist
    await conn.execute("ALTER TABLE schema_migrations ADD COLUMN IF NOT EXISTS id TEXT")
    return "id"


async def run_migrations() -> None:
    pool = await get_pg_pool()
    if pool is None:
        print("[migrate] PG_DSN not set; skipping migrations")
        return

    migrations_dir = Path(__file__).resolve().parents[1] / "migrations"
    sql_files: List[Path] = sorted(migrations_dir.glob("*.sql"))
    async with pool.acquire() as conn:
        ident_col = await _ensure_migrations_table(conn)
        # If the chosen ident_col is 'version', prefer a safer text column for tracking if available
        if ident_col == "version":
            if await conn.fetchval(
                "SELECT 1 FROM information_schema.columns WHERE table_name='schema_migrations' AND column_name='filename'"
            ):
                ident_col = "filename"
            elif await conn.fetchval(
                "SELECT 1 FROM information_schema.columns WHERE table_name='schema_migrations' AND column_name='name'"
            ):
                ident_col = "name"
            elif await conn.fetchval(
                "SELECT 1 FROM information_schema.columns WHERE table_name='schema_migrations' AND column_name='id'"
            ):
                ident_col = "id"
        # Inspect columns and nullability
        cols = await conn.fetch(
            """
            SELECT column_name, is_nullable, column_default
            , data_type
            FROM information_schema.columns
            WHERE table_name='schema_migrations'
            """
        )
        col_meta = {
            r["column_name"]: {
                "nullable": (r["is_nullable"] == "YES"),
                "default": r["column_default"],
                "type": r["data_type"],
            }
            for r in cols
        }
        for sql in sql_files:
            migration_id = sql.name
            row = None
            if ident_col in col_meta:
                # Note: ident_col is from database introspection (fixed set: filename/name/id/version)
                row = await conn.fetchrow(
                    f"SELECT 1 FROM schema_migrations WHERE {ident_col}=$1",  # nosec B608
                    migration_id,
                )
            if row:
                continue
            print(f"[migrate] applying {migration_id}")
            await conn.execute(sql.read_text(encoding="utf-8"))
            # Do not track shim bootstrap files explicitly (avoid conflicting legacy schemas)
            if migration_id.startswith("000_"):
                continue
            # Build dynamic insert covering required non-null, no-default columns
            insert_cols = []
            insert_vals = []
            if ident_col in col_meta:
                insert_cols.append(ident_col)
                insert_vals.append(migration_id)
            # Common required columns to satisfy
            for col_name, meta in col_meta.items():
                if col_name == ident_col:
                    continue
                if meta["nullable"] or meta["default"]:
                    continue
                # Provide sensible filler values based on type
                dtype = (meta["type"] or "").lower()
                if "int" in dtype or dtype in ("integer", "smallint", "bigint"):
                    filler = 1
                elif "timestamp" in dtype or "date" in dtype:
                    # Let database default handle if any, otherwise supply now()
                    # We'll skip explicit value and rely on DEFAULT if possible
                    continue
                else:
                    filler = migration_id
                insert_cols.append(col_name)
                insert_vals.append(filler)
            if insert_cols:
                placeholders = ",".join(f"${i+1}" for i in range(len(insert_vals)))
                cols_sql = ",".join(insert_cols)
                try:
                    # Column names from database introspection (information_schema.columns),
                    # not user input - safe for dynamic SQL construction
                    await conn.execute(
                        f"INSERT INTO schema_migrations ({cols_sql}) VALUES ({placeholders})",  # nosec B608
                        *insert_vals,
                    )
                except Exception:
                    # Be permissive to legacy schemas; if insert fails, continue
                    pass
            else:
                # If no identifiable columns, insert a timestamp-only row
                await conn.execute("INSERT INTO schema_migrations DEFAULT VALUES")


if __name__ == "__main__":
    asyncio.run(run_migrations())
