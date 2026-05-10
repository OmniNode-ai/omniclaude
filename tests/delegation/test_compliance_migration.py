# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for migration 003: tokens_to_compliance + compliance_attempts columns (OMN-10789).

Verifies:
- Migration applies cleanly on a fresh (empty) database
- Migration applies cleanly on a database already at migration 002
- PRAGMA table_info includes both new columns after migration
- write_delegation_event round-trips tokens_to_compliance and compliance_attempts
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from omniclaude.delegation.sqlite_adapter import (
    ModelDelegationEvent,
    SQLiteProjectionAdapter,
)

_MIGRATIONS_DIR = (
    Path(__file__).parents[2] / "src" / "omniclaude" / "delegation" / "migrations"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _column_names(conn: sqlite3.Connection, table: str) -> list[str]:
    """Return column names for *table* via PRAGMA table_info."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [r[1] for r in rows]


def _manually_apply_up_to_002(conn: sqlite3.Connection) -> None:
    """Apply migrations 001 and 002 without the adapter (simulates pre-003 state)."""
    import time

    conn.executescript(
        (_MIGRATIONS_DIR / "001_create_delegation_tables.sql").read_text()
    )
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, applied_at, description) VALUES (?, ?, ?)",
        ("001", time.time(), "Create delegation projection tables"),
    )

    migration_sql = "\n".join(
        line
        for line in (_MIGRATIONS_DIR / "002_align_with_projection_handler.sql")
        .read_text()
        .splitlines()
        if not line.lstrip().startswith("--")
    )
    for stmt in migration_sql.strip().split(";"):
        stmt = stmt.strip()
        if not stmt:
            continue
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError as exc:
            if "duplicate column" not in str(exc):
                raise
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, applied_at, description) VALUES (?, ?, ?)",
        ("002", time.time(), "Align with projection handler schema"),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMigration003FreshDB:
    """Migration 003 applies cleanly on a brand-new database."""

    def test_fresh_db_includes_compliance_columns(self) -> None:
        conn = sqlite3.connect(":memory:")
        adapter = SQLiteProjectionAdapter(conn)

        cols = _column_names(conn, "delegation_events")
        assert "tokens_to_compliance" in cols
        assert "compliance_attempts" in cols

        applied = adapter.get_applied_migrations()
        assert "003" in applied
        adapter.close()

    def test_fresh_db_all_migrations_applied(self) -> None:
        conn = sqlite3.connect(":memory:")
        adapter = SQLiteProjectionAdapter(conn)

        applied = adapter.get_applied_migrations()
        assert applied == ["001", "002", "003"]
        adapter.close()


@pytest.mark.unit
class TestMigration003FromV002:
    """Migration 003 applies cleanly on a database already at version 002."""

    def test_upgrade_from_002_adds_columns(self) -> None:
        conn = sqlite3.connect(":memory:")
        _manually_apply_up_to_002(conn)

        # Confirm columns are absent before adapter construction.
        cols_before = _column_names(conn, "delegation_events")
        assert "tokens_to_compliance" not in cols_before
        assert "compliance_attempts" not in cols_before

        # Constructing the adapter triggers migration 003.
        adapter = SQLiteProjectionAdapter(conn)

        cols_after = _column_names(conn, "delegation_events")
        assert "tokens_to_compliance" in cols_after
        assert "compliance_attempts" in cols_after

        applied = adapter.get_applied_migrations()
        assert "003" in applied
        adapter.close()


@pytest.mark.unit
class TestMigration003PragmaTableInfo:
    """PRAGMA table_info reflects both new columns with correct types and defaults."""

    def test_column_types_and_defaults(self) -> None:
        conn = sqlite3.connect(":memory:")
        _adapter = SQLiteProjectionAdapter(conn)

        rows = conn.execute("PRAGMA table_info(delegation_events)").fetchall()
        col_map = {r[1]: {"type": r[2], "notnull": r[3], "default": r[4]} for r in rows}

        ttc = col_map["tokens_to_compliance"]
        assert ttc["type"] == "INTEGER"
        assert ttc["notnull"] == 1
        assert ttc["default"] == "0"

        ca = col_map["compliance_attempts"]
        assert ca["type"] == "INTEGER"
        assert ca["notnull"] == 1
        assert ca["default"] == "1"
        _adapter.close()


@pytest.mark.unit
class TestWriteDelegationEventCompliance:
    """write_delegation_event round-trips tokens_to_compliance and compliance_attempts."""

    def test_write_and_read_compliance_fields(self) -> None:
        conn = sqlite3.connect(":memory:")
        adapter = SQLiteProjectionAdapter(conn)

        event = ModelDelegationEvent(
            correlation_id="corr-compliance-001",
            session_id="sess-001",
            task_type="document",
            delegated_to="qwen3-coder",
            model_name="qwen3-coder-30b",
            tokens_to_compliance=4200,
            compliance_attempts=3,
        )
        ok = adapter.write_delegation_event(event)
        assert ok is True

        rows = adapter.query_delegation_events(session_id="sess-001")
        assert len(rows) == 1
        row = rows[0]
        assert row.tokens_to_compliance == 4200
        assert row.compliance_attempts == 3
        adapter.close()

    def test_default_compliance_values(self) -> None:
        conn = sqlite3.connect(":memory:")
        adapter = SQLiteProjectionAdapter(conn)

        event = ModelDelegationEvent(
            correlation_id="corr-compliance-defaults",
            session_id="sess-defaults",
            task_type="document",
        )
        ok = adapter.write_delegation_event(event)
        assert ok is True

        rows = adapter.query_delegation_events(session_id="sess-defaults")
        assert len(rows) == 1
        row = rows[0]
        assert row.tokens_to_compliance == 0
        assert row.compliance_attempts == 1
        adapter.close()

    def test_upsert_updates_compliance_fields(self) -> None:
        conn = sqlite3.connect(":memory:")
        adapter = SQLiteProjectionAdapter(conn)

        event_v1 = ModelDelegationEvent(
            correlation_id="corr-upsert-compliance",
            session_id="sess-upsert",
            tokens_to_compliance=100,
            compliance_attempts=1,
        )
        adapter.write_delegation_event(event_v1)

        event_v2 = ModelDelegationEvent(
            correlation_id="corr-upsert-compliance",
            session_id="sess-upsert",
            tokens_to_compliance=5500,
            compliance_attempts=4,
        )
        adapter.write_delegation_event(event_v2)

        rows = adapter.query_delegation_events(session_id="sess-upsert")
        assert len(rows) == 1
        row = rows[0]
        assert row.tokens_to_compliance == 5500
        assert row.compliance_attempts == 4
        adapter.close()
