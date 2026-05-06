# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for SQLiteProjectionAdapter (OMN-10618)."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pydantic import ValidationError

from omniclaude.delegation.sqlite_adapter import (
    ModelDelegationEvent,
    ModelEventLogEnvelope,
    ModelLlmCallMetric,
    ModelSavingsEstimate,
    SQLiteProjectionAdapter,
)


@pytest.fixture
def adapter(tmp_path: Path) -> SQLiteProjectionAdapter:
    db = SQLiteProjectionAdapter(db_path=tmp_path / "test_delegation.sqlite")
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
        "model_id": "qwen3-coder-30b",
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
        a1 = SQLiteProjectionAdapter(db_path=db_path)
        a1.close()
        a2 = SQLiteProjectionAdapter(db_path=db_path)
        versions = a2.get_applied_migrations()
        a2.close()
        assert versions.count("001") == 1


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
