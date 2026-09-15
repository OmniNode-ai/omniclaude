# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for SQLiteProjectionAdapter (OMN-10618)."""

from __future__ import annotations

import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pydantic import ValidationError

import omniclaude.delegation.sqlite_adapter as sqlite_adapter_module
from omniclaude.delegation.sqlite_adapter import (
    ModelDelegationEvent,
    ModelEventLogEnvelope,
    ModelLlmCallMetric,
    ModelSavingsEstimate,
    SQLiteProjectionAdapter,
    make_adapter,
)
from tests.constants import MODEL_LOCAL_CODER


@pytest.fixture
def adapter() -> SQLiteProjectionAdapter:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    db = SQLiteProjectionAdapter(conn)
    yield db
    db.close()


def _delegation_event(
    correlation_id: str = "corr-001", **overrides: object
) -> ModelDelegationEvent:
    base = {
        "correlation_id": correlation_id,
        "session_id": "sess-abc",
        "tool_use_id": "tu-1",
        "hook_name": "PostToolUse",
        "task_type": "code-review",
        "delegated_to": "researcher",
        "model_name": "qwen3-30b",
        "quality_gate_passed": True,
        "quality_gate_detail": "all gates green",
        "latency_ms": 420,
        "input_hash": "sha256:aabbcc",
        "input_redaction_policy": "hash_only",
        "contract_version": "v1",
        "created_at": time.time(),
    }
    base.update(overrides)
    return ModelDelegationEvent(**base)


def _llm_metric(
    input_hash: str = "sha256:aabbcc", **overrides: object
) -> ModelLlmCallMetric:
    base = {
        "input_hash": input_hash,
        "model_id": MODEL_LOCAL_CODER,
        "prompt_tokens": 1024,
        "completion_tokens": 512,
        "estimated_cost_usd": 0.001,
        "usage_source": "estimated",
        "token_provenance": "local",
        "created_at": time.time(),
    }
    base.update(overrides)
    return ModelLlmCallMetric(**base)


def _savings_estimate(
    session_id: str = "sess-abc", ts: float | None = None, **overrides: object
) -> ModelSavingsEstimate:
    base = {
        "session_id": session_id,
        "event_timestamp": ts or time.time(),
        "model_local": "qwen3-30b",
        "model_cloud_baseline": "claude-sonnet-4-6",
        "local_cost_usd": 0.001,
        "cloud_cost_usd": 0.015,
        "savings_usd": 0.014,
        "baseline_model": "claude-sonnet-4-6",
        "pricing_manifest_version": "v1",
        "savings_method": "token_diff",
        "usage_source": "estimated",
        "created_at": time.time(),
    }
    base.update(overrides)
    return ModelSavingsEstimate(**base)


class TestMigration:
    def test_tables_created_on_first_use(
        self, adapter: SQLiteProjectionAdapter
    ) -> None:
        tables = {
            r[0]
            for r in adapter._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "schema_migrations" in tables
        assert "delegation_events" in tables
        assert "llm_call_metrics" in tables
        assert "savings_estimates" in tables
        assert "delegation_event_log" in tables

    def test_migration_version_recorded(self, adapter: SQLiteProjectionAdapter) -> None:
        versions = adapter.get_applied_migrations()
        assert "001" in versions

    def test_migration_idempotent(self, tmp_path: Path) -> None:
        db_path = tmp_path / "idempotent.sqlite"
        a1 = make_adapter(db_path)
        a1.close()
        a2 = make_adapter(db_path)
        versions = a2.get_applied_migrations()
        a2.close()
        assert versions.count("001") == 1

    def test_make_adapter_creates_on_disk_db(self, tmp_path: Path) -> None:
        db_path = tmp_path / "smoke.sqlite"
        adapter = make_adapter(db_path)
        adapter.close()
        assert db_path.exists()

    def test_canonical_reconcile_preserves_rows_columns_and_indexes(
        self, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "warm-canonical.sqlite"
        conn = sqlite3.connect(db_path)
        conn.executescript(
            (sqlite_adapter_module._MIGRATION_SQL).read_text()
            + (sqlite_adapter_module._MIGRATION_002_SQL).read_text()
            + (sqlite_adapter_module._MIGRATION_003_SQL).read_text()
        )
        conn.execute(
            "INSERT INTO delegation_events "
            "(correlation_id, task_type, created_at, delegated_by) "
            "VALUES (?, ?, ?, ?)",
            ("warm-001", "preserve", 123.5, "owner"),
        )
        conn.execute(
            "INSERT INTO delegation_events "
            "(id, correlation_id, task_type, created_at) VALUES (?, ?, ?, ?)",
            (42, "warm-042", "high-water", 124.0),
        )
        conn.execute(
            "CREATE INDEX idx_legacy_delegation_task ON delegation_events(task_type)"
        )
        conn.commit()
        conn.close()

        adapter = make_adapter(db_path)
        try:
            row = next(
                row
                for row in adapter.query_delegation_events()
                if row.correlation_id == "warm-001"
            )
            assert row.correlation_id == "warm-001"
            assert row.task_type == "preserve"
            assert row.created_at == 123.5
            with sqlite3.connect(db_path) as check:
                columns = {
                    record[1]
                    for record in check.execute("PRAGMA table_info(delegation_events)")
                }
                indexes = {
                    record[1]
                    for record in check.execute("PRAGMA index_list(delegation_events)")
                }
                created_at = next(
                    record
                    for record in check.execute("PRAGMA table_info(delegation_events)")
                    if record[1] == "created_at"
                )
            assert {"cost_usd", "tenant_id", "writer_identity", "written_at"} <= columns
            assert "idx_legacy_delegation_task" in indexes
            assert created_at[4] is not None
            assert adapter.write_delegation_event(_delegation_event("warm-043"))
            with sqlite3.connect(db_path) as check:
                assert (
                    check.execute(
                        "SELECT id FROM delegation_events WHERE correlation_id = ?",
                        ("warm-043",),
                    ).fetchone()[0]
                    > 42
                )
        finally:
            adapter.close()

    def test_canonical_reconcile_locks_schema_before_capturing_metadata(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A concurrent extension cannot land after M004 captures its snapshot."""
        db_path = tmp_path / "schema-lock.sqlite"
        setup = sqlite3.connect(db_path)
        setup.executescript(
            (sqlite_adapter_module._MIGRATION_SQL).read_text()
            + (sqlite_adapter_module._MIGRATION_002_SQL).read_text()
            + (sqlite_adapter_module._MIGRATION_003_SQL).read_text()
        )
        setup.commit()
        setup.close()

        metadata_read_started = threading.Event()
        contender_finished = threading.Event()
        contender_outcome: list[str] = []

        original_read_metadata = SQLiteProjectionAdapter._read_reconciliation_metadata

        def pause_after_metadata_capture(
            adapter: SQLiteProjectionAdapter,
        ) -> tuple[set[str], list[str], int | None]:
            metadata = original_read_metadata(adapter)
            metadata_read_started.set()
            assert contender_finished.wait(timeout=5)
            return metadata

        monkeypatch.setattr(
            SQLiteProjectionAdapter,
            "_read_reconciliation_metadata",
            pause_after_metadata_capture,
        )

        def extend_schema() -> None:
            if not metadata_read_started.wait(timeout=5):
                contender_outcome.append("migration metadata read did not start")
                contender_finished.set()
                return
            contender = sqlite3.connect(db_path, timeout=0)
            try:
                contender.execute(
                    "ALTER TABLE delegation_events ADD COLUMN concurrent_extension TEXT"
                )
                contender.commit()
                contender_outcome.append("extension succeeded")
            except sqlite3.OperationalError as exc:
                contender_outcome.append(str(exc))
            finally:
                contender.close()
                contender_finished.set()

        source = sqlite3.connect(db_path)
        contender_thread = threading.Thread(target=extend_schema)
        contender_thread.start()
        adapter = SQLiteProjectionAdapter(source)
        contender_thread.join(timeout=5)

        try:
            assert not contender_thread.is_alive()
            assert contender_outcome and "locked" in contender_outcome[0]
            with sqlite3.connect(db_path) as check:
                columns = {
                    record[1]
                    for record in check.execute("PRAGMA table_info(delegation_events)")
                }
                versions = {
                    record[0]
                    for record in check.execute("SELECT version FROM schema_migrations")
                }
            assert "concurrent_extension" not in columns
            assert "004" in versions
        finally:
            adapter.close()

    def test_canonical_reconcile_marker_failure_rolls_back_schema(
        self, tmp_path: Path
    ) -> None:
        """A rejected 004 marker restores the old schema and leaves no transaction."""
        db_path = tmp_path / "marker-rollback.sqlite"
        setup = sqlite3.connect(db_path)
        setup.executescript(
            (sqlite_adapter_module._MIGRATION_SQL).read_text()
            + (sqlite_adapter_module._MIGRATION_002_SQL).read_text()
            + (sqlite_adapter_module._MIGRATION_003_SQL).read_text()
        )
        setup.execute(
            "INSERT INTO delegation_events (correlation_id, task_type, created_at) "
            "VALUES (?, ?, ?)",
            ("marker-rollback-001", "unchanged", 10.0),
        )
        setup.execute(
            "CREATE TRIGGER reject_migration_004 "
            "BEFORE INSERT ON schema_migrations "
            "WHEN NEW.version = '004' "
            "BEGIN SELECT RAISE(ABORT, 'reject migration 004'); END"
        )
        setup.commit()
        setup.close()

        source = sqlite3.connect(db_path)
        try:
            with pytest.raises(sqlite3.IntegrityError, match="reject migration 004"):
                SQLiteProjectionAdapter(source)

            assert not source.in_transaction
            row = source.execute(
                "SELECT correlation_id, task_type, created_at FROM delegation_events"
            ).fetchone()
            columns = {
                record[1]
                for record in source.execute("PRAGMA table_info(delegation_events)")
            }
            versions = {
                record[0]
                for record in source.execute("SELECT version FROM schema_migrations")
            }
            assert tuple(row) == ("marker-rollback-001", "unchanged", 10.0)
            assert "writer_identity" not in columns
            assert {"001", "002", "003"} <= versions
            assert "004" not in versions

            source.execute("CREATE TABLE marker_cleanup_proof (id INTEGER)")
            source.execute("DROP TRIGGER reject_migration_004")
            source.commit()

            adapter = SQLiteProjectionAdapter(source)
            try:
                assert "004" in adapter.get_applied_migrations()
            finally:
                adapter.close()
        finally:
            if source:
                source.close()

    def test_canonical_reconcile_refusal_rolls_back_its_schema_lock(
        self, tmp_path: Path
    ) -> None:
        """Unsupported columns remain intact and do not leave M004 open."""
        db_path = tmp_path / "unsupported-column.sqlite"
        setup = sqlite3.connect(db_path)
        setup.executescript(
            (sqlite_adapter_module._MIGRATION_SQL).read_text()
            + (sqlite_adapter_module._MIGRATION_002_SQL).read_text()
            + (sqlite_adapter_module._MIGRATION_003_SQL).read_text()
        )
        setup.execute(
            "ALTER TABLE delegation_events ADD COLUMN unsupported_extension TEXT"
        )
        setup.commit()
        setup.close()

        source = sqlite3.connect(db_path)
        try:
            with pytest.raises(RuntimeError, match="unsupported columns"):
                SQLiteProjectionAdapter(source)

            assert not source.in_transaction
            source.execute("CREATE TABLE refusal_cleanup_proof (id INTEGER)")
            source.commit()
        finally:
            source.close()

        with sqlite3.connect(db_path) as check:
            columns = {
                record[1]
                for record in check.execute("PRAGMA table_info(delegation_events)")
            }
            versions = {
                record[0]
                for record in check.execute("SELECT version FROM schema_migrations")
            }
            tables = {
                record[0]
                for record in check.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        assert "unsupported_extension" in columns
        assert "004" not in versions
        assert "refusal_cleanup_proof" in tables

    def test_canonical_reconcile_rolls_back_on_schema_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db_path = tmp_path / "rollback.sqlite"
        conn = sqlite3.connect(db_path)
        conn.executescript(
            (sqlite_adapter_module._MIGRATION_SQL).read_text()
            + (sqlite_adapter_module._MIGRATION_002_SQL).read_text()
            + (sqlite_adapter_module._MIGRATION_003_SQL).read_text()
        )
        conn.execute(
            "INSERT INTO delegation_events (correlation_id, task_type, created_at) "
            "VALUES (?, ?, ?)",
            ("rollback-001", "unchanged", 10.0),
        )
        conn.commit()
        conn.close()
        monkeypatch.setitem(
            sqlite_adapter_module._CANONICAL_COLUMN_DEFINITIONS,
            "migration_failure",
            "THIS IS INVALID SQL",
        )

        with pytest.raises(sqlite3.OperationalError):
            make_adapter(db_path)

        with sqlite3.connect(db_path) as check:
            row = check.execute(
                "SELECT correlation_id, task_type, created_at FROM delegation_events"
            ).fetchone()
            tables = {
                record[0]
                for record in check.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            versions = {
                record[0]
                for record in check.execute("SELECT version FROM schema_migrations")
            }
        assert row == ("rollback-001", "unchanged", 10.0)
        assert "delegation_events_v004" not in tables
        assert "004" not in versions

    def test_canonical_reconcile_rolls_back_during_index_replay(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db_path = tmp_path / "index-rollback.sqlite"
        conn = sqlite3.connect(db_path)
        conn.executescript(
            (sqlite_adapter_module._MIGRATION_SQL).read_text()
            + (sqlite_adapter_module._MIGRATION_002_SQL).read_text()
            + (sqlite_adapter_module._MIGRATION_003_SQL).read_text()
        )
        conn.execute(
            "INSERT INTO delegation_events (correlation_id, task_type, created_at) "
            "VALUES (?, ?, ?)",
            ("index-rollback-001", "unchanged", 10.0),
        )
        conn.execute(
            "CREATE INDEX idx_index_rollback_task ON delegation_events(task_type)"
        )
        conn.commit()
        conn.close()

        def fail_replay(_conn: sqlite3.Connection, _statement: str) -> None:
            raise RuntimeError("injected index replay failure")

        monkeypatch.setattr(sqlite_adapter_module, "_recreate_index", fail_replay)
        with pytest.raises(RuntimeError, match="index replay failure"):
            make_adapter(db_path)

        with sqlite3.connect(db_path) as check:
            row = check.execute(
                "SELECT correlation_id, task_type, created_at FROM delegation_events"
            ).fetchone()
            indexes = {
                record[1]
                for record in check.execute("PRAGMA index_list(delegation_events)")
            }
            versions = {
                record[0]
                for record in check.execute("SELECT version FROM schema_migrations")
            }
        assert row == ("index-rollback-001", "unchanged", 10.0)
        assert "idx_index_rollback_task" in indexes
        assert "004" not in versions


class TestDelegationEvent:
    def test_rejects_unknown_input_fields(self) -> None:
        with pytest.raises(ValidationError):
            _delegation_event(unexpected_field="drift")

    def test_write_and_query(self, adapter: SQLiteProjectionAdapter) -> None:
        ok = adapter.write_delegation_event(_delegation_event())
        assert ok is True
        rows = adapter.query_delegation_events()
        assert len(rows) == 1
        assert rows[0].correlation_id == "corr-001"

    def test_upsert_idempotency(self, adapter: SQLiteProjectionAdapter) -> None:
        adapter.write_delegation_event(_delegation_event(model_name="model-a"))
        adapter.write_delegation_event(_delegation_event(model_name="model-b"))
        rows = adapter.query_delegation_events()
        assert len(rows) == 1
        assert rows[0].model_name == "model-b"

    def test_query_by_session_id(self, adapter: SQLiteProjectionAdapter) -> None:
        adapter.write_delegation_event(_delegation_event("corr-1", session_id="sess-x"))
        adapter.write_delegation_event(_delegation_event("corr-2", session_id="sess-y"))
        rows = adapter.query_delegation_events(session_id="sess-x")
        assert len(rows) == 1
        assert rows[0].correlation_id == "corr-1"

    def test_query_limit(self, adapter: SQLiteProjectionAdapter) -> None:
        for i in range(10):
            adapter.write_delegation_event(_delegation_event(f"corr-{i}"))
        rows = adapter.query_delegation_events(limit=5)
        assert len(rows) == 5

    def test_quality_gate_passed_boolean_roundtrip(
        self, adapter: SQLiteProjectionAdapter
    ) -> None:
        adapter.write_delegation_event(_delegation_event(quality_gate_passed=True))
        row = adapter.query_delegation_events()[0]
        assert row.quality_gate_passed == 1

    def test_concurrent_writes_are_serialized(
        self, adapter: SQLiteProjectionAdapter
    ) -> None:
        def write(index: int) -> bool:
            return adapter.write_delegation_event(_delegation_event(f"corr-{index}"))

        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(write, range(20)))

        assert all(results)
        assert len(adapter.query_delegation_events(limit=25)) == 20


class TestLlmCallMetric:
    def test_write_and_read(self, adapter: SQLiteProjectionAdapter) -> None:
        ok = adapter.write_llm_call_metric(_llm_metric())
        assert ok is True
        rows = adapter._conn.execute("SELECT * FROM llm_call_metrics").fetchall()
        assert len(rows) == 1
        assert rows[0]["input_hash"] == "sha256:aabbcc"

    def test_upsert_idempotency(self, adapter: SQLiteProjectionAdapter) -> None:
        adapter.write_llm_call_metric(_llm_metric(prompt_tokens=100))
        adapter.write_llm_call_metric(_llm_metric(prompt_tokens=200))
        rows = adapter._conn.execute("SELECT * FROM llm_call_metrics").fetchall()
        assert len(rows) == 1
        assert rows[0]["prompt_tokens"] == 200


class TestSavingsEstimate:
    def test_write_and_summary(self, adapter: SQLiteProjectionAdapter) -> None:
        ts = time.time()
        ok = adapter.write_savings_estimate(_savings_estimate(ts=ts))
        assert ok is True
        summary = adapter.query_savings_summary()
        assert summary.event_count == 1
        assert abs(summary.total_savings_usd - 0.014) < 1e-6

    def test_upsert_idempotency(self, adapter: SQLiteProjectionAdapter) -> None:
        ts = time.time()
        adapter.write_savings_estimate(_savings_estimate(ts=ts, savings_usd=0.010))
        adapter.write_savings_estimate(_savings_estimate(ts=ts, savings_usd=0.020))
        rows = adapter._conn.execute("SELECT * FROM savings_estimates").fetchall()
        assert len(rows) == 1
        assert abs(rows[0]["savings_usd"] - 0.020) < 1e-6

    def test_composite_key_different_models_are_separate_rows(
        self, adapter: SQLiteProjectionAdapter
    ) -> None:
        ts = time.time()
        adapter.write_savings_estimate(_savings_estimate(ts=ts, model_local="modelA"))
        adapter.write_savings_estimate(_savings_estimate(ts=ts, model_local="modelB"))
        rows = adapter._conn.execute("SELECT * FROM savings_estimates").fetchall()
        assert len(rows) == 2

    def test_summary_scoped_to_session(self, adapter: SQLiteProjectionAdapter) -> None:
        adapter.write_savings_estimate(_savings_estimate("sess-1", savings_usd=0.010))
        adapter.write_savings_estimate(_savings_estimate("sess-2", savings_usd=0.050))
        summary = adapter.query_savings_summary(session_id="sess-1")
        assert summary.event_count == 1
        assert abs(summary.total_savings_usd - 0.010) < 1e-6

    def test_empty_summary_returns_zeros(
        self, adapter: SQLiteProjectionAdapter
    ) -> None:
        summary = adapter.query_savings_summary()
        assert summary.event_count == 0
        assert summary.total_savings_usd == 0.0
        assert summary.total_local_cost_usd == 0.0
        assert summary.total_cloud_cost_usd == 0.0


class TestEventLog:
    def test_append_is_not_deduped(self, adapter: SQLiteProjectionAdapter) -> None:
        envelope = ModelEventLogEnvelope(payload='{"type": "test"}')
        adapter.append_event_log(envelope)
        adapter.append_event_log(envelope)
        rows = adapter._conn.execute("SELECT * FROM delegation_event_log").fetchall()
        assert len(rows) == 2

    def test_envelope_payload_stored_verbatim(
        self, adapter: SQLiteProjectionAdapter
    ) -> None:
        import json

        raw = json.dumps({"type": "test", "nested": {"a": 1}})
        envelope = ModelEventLogEnvelope(payload=raw)
        adapter.append_event_log(envelope)
        row = adapter._conn.execute(
            "SELECT envelope FROM delegation_event_log"
        ).fetchone()
        parsed = json.loads(row[0])
        assert parsed["type"] == "test"
        assert parsed["nested"]["a"] == 1


@pytest.mark.unit
class TestUpsertQuery:
    """ProtocolProjectionDatabaseSync generic upsert/query API (OMN-10718)."""

    def test_upsert_writes_row_to_delegation_events(
        self, adapter: SQLiteProjectionAdapter
    ) -> None:
        row: dict[str, object] = {
            "correlation_id": "upsert-001",
            "session_id": "sess-u1",
            "task_type": "test",
            "delegated_to": "Qwen3-Coder-30B",
            "model_name": "Qwen3-Coder-30B",
            "quality_gate_passed": True,
            "delegation_latency_ms": 350,
        }
        ok = adapter.upsert("delegation_events", "correlation_id", row)
        assert ok is True
        rows = adapter._conn.execute(
            "SELECT * FROM delegation_events WHERE correlation_id = 'upsert-001'"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["task_type"] == "test"
        assert rows[0]["delegated_to"] == "Qwen3-Coder-30B"
        assert rows[0]["latency_ms"] == 350

    def test_upsert_deduplicates_on_correlation_id(
        self, adapter: SQLiteProjectionAdapter
    ) -> None:
        row: dict[str, object] = {
            "correlation_id": "dedup-001",
            "task_type": "document",
            "delegated_to": "ModelA",
            "model_name": "ModelA",
            "quality_gate_passed": False,
            "delegation_latency_ms": 100,
        }
        adapter.upsert("delegation_events", "correlation_id", row)
        row_updated = {**row, "delegated_to": "ModelB", "model_name": "ModelB"}
        adapter.upsert("delegation_events", "correlation_id", row_updated)
        rows = adapter._conn.execute(
            "SELECT * FROM delegation_events WHERE correlation_id = 'dedup-001'"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["delegated_to"] == "ModelB"

    def test_upsert_unknown_table_returns_false(
        self, adapter: SQLiteProjectionAdapter
    ) -> None:
        ok = adapter.upsert("nonexistent_table", "id", {"id": "x"})
        assert ok is False

    def test_query_returns_all_rows_without_filter(
        self, adapter: SQLiteProjectionAdapter
    ) -> None:
        for i in range(3):
            adapter.upsert(
                "delegation_events",
                "correlation_id",
                {
                    "correlation_id": f"q-{i}",
                    "task_type": "test",
                    "delegated_to": "ModelX",
                    "model_name": "ModelX",
                    "quality_gate_passed": True,
                    "delegation_latency_ms": 10,
                },
            )
        rows = adapter.query("delegation_events")
        assert len(rows) == 3

    def test_query_with_filter(self, adapter: SQLiteProjectionAdapter) -> None:
        adapter.upsert(
            "delegation_events",
            "correlation_id",
            {
                "correlation_id": "filter-a",
                "session_id": "sess-x",
                "task_type": "test",
                "delegated_to": "ModelX",
                "model_name": "ModelX",
                "quality_gate_passed": True,
                "delegation_latency_ms": 10,
            },
        )
        adapter.upsert(
            "delegation_events",
            "correlation_id",
            {
                "correlation_id": "filter-b",
                "session_id": "sess-y",
                "task_type": "test",
                "delegated_to": "ModelX",
                "model_name": "ModelX",
                "quality_gate_passed": True,
                "delegation_latency_ms": 10,
            },
        )
        rows = adapter.query("delegation_events", filters={"session_id": "sess-x"})
        assert len(rows) == 1
        assert rows[0]["correlation_id"] == "filter-a"

    def test_upsert_extra_fields_are_silently_dropped(
        self, adapter: SQLiteProjectionAdapter
    ) -> None:
        row: dict[str, object] = {
            "correlation_id": "extra-001",
            "task_type": "research",
            "delegated_to": "ModelQ",
            "model_name": "ModelQ",
            "quality_gate_passed": True,
            "delegation_latency_ms": 200,
            "delegated_by": "onex.delegate-skill.inprocess",  # not in SQLite schema
            "repo": "omniclaude",  # not in SQLite schema
            "is_shadow": False,  # not in SQLite schema
            "timestamp": "2026-05-09T00:00:00Z",  # not in SQLite schema
        }
        ok = adapter.upsert("delegation_events", "correlation_id", row)
        assert ok is True
        rows = adapter._conn.execute(
            "SELECT * FROM delegation_events WHERE correlation_id = 'extra-001'"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["latency_ms"] == 200
