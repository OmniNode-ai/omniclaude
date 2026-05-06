# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""SQLite projection adapter for delegation telemetry.

Lightweight persistence layer for customer environments — no Postgres required.
Database location: ~/.omninode/delegation/delegation.sqlite
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

_MIGRATION_SQL = (
    Path(__file__).parent / "migrations" / "001_create_delegation_tables.sql"
)
_DEFAULT_DB_PATH = Path.home() / ".omninode" / "delegation" / "delegation.sqlite"
_MIGRATION_VERSION = "001"
_MIGRATION_DESCRIPTION = "Create delegation projection tables"


# ---------------------------------------------------------------------------
# Input models
# ---------------------------------------------------------------------------


class ModelDelegationEvent(BaseModel):
    """Input for write_delegation_event."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    correlation_id: str
    session_id: str | None = None
    tool_use_id: str | None = None
    hook_name: str | None = None
    task_type: str = ""
    delegated_to: str = ""
    model_name: str = ""
    quality_gate_passed: bool = False
    quality_gate_detail: str | None = None
    latency_ms: int | None = None
    input_hash: str | None = None
    input_redaction_policy: str = "hash_only"
    contract_version: str = "v1"
    created_at: float = Field(default_factory=time.time)


class ModelLlmCallMetric(BaseModel):
    """Input for write_llm_call_metric."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    input_hash: str
    model_id: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost_usd: float = 0.0
    usage_source: str = "estimated"
    token_provenance: str | None = None
    created_at: float = Field(default_factory=time.time)


class ModelSavingsEstimate(BaseModel):
    """Input for write_savings_estimate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: str
    event_timestamp: float
    model_local: str
    model_cloud_baseline: str
    local_cost_usd: float = 0.0
    cloud_cost_usd: float = 0.0
    savings_usd: float = 0.0
    baseline_model: str = ""
    pricing_manifest_version: str = "v1"
    savings_method: str = "token_diff"
    usage_source: str = "estimated"
    created_at: float = Field(default_factory=time.time)


class ModelEventLogEnvelope(BaseModel):
    """Input for append_event_log — typed wrapper around a pre-serialized envelope."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    payload: str


# ---------------------------------------------------------------------------
# Output models
# ---------------------------------------------------------------------------


class ModelDelegationEventRow(BaseModel):
    """Row returned by query_delegation_events."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: int
    correlation_id: str
    session_id: str | None = None
    tool_use_id: str | None = None
    hook_name: str | None = None
    task_type: str = ""
    delegated_to: str = ""
    model_name: str = ""
    quality_gate_passed: int = 0
    quality_gate_detail: str | None = None
    latency_ms: int | None = None
    input_hash: str | None = None
    input_redaction_policy: str = "hash_only"
    contract_version: str = "v1"
    created_at: float = 0.0


class ModelSavingsSummary(BaseModel):
    """Aggregate returned by query_savings_summary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_count: int = 0
    total_local_cost_usd: float = 0.0
    total_cloud_cost_usd: float = 0.0
    total_savings_usd: float = 0.0


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class SQLiteProjectionAdapter:
    """SQLite-backed adapter for delegation projection tables.

    Implements the same logical interface as the Postgres projection layer:
    write_delegation_event, write_llm_call_metric, write_savings_estimate,
    append_event_log, query_delegation_events, query_savings_summary.

    Thread-safe via an internal lock around the shared SQLite connection.
    Each instance owns one connection.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or _DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._apply_migrations()

    # ------------------------------------------------------------------
    # Migration
    # ------------------------------------------------------------------

    def _apply_migrations(self) -> None:
        ddl = _MIGRATION_SQL.read_text()
        with self._lock:
            self._conn.executescript(ddl)
            self._conn.execute(
                "INSERT OR IGNORE INTO schema_migrations (version, applied_at, description) VALUES (?, ?, ?)",
                (_MIGRATION_VERSION, time.time(), _MIGRATION_DESCRIPTION),
            )
            self._conn.commit()
        logger.debug("Ensured migration %s is applied", _MIGRATION_VERSION)

    # ------------------------------------------------------------------
    # Write methods
    # ------------------------------------------------------------------

    def write_delegation_event(self, event: ModelDelegationEvent) -> bool:
        """UPSERT a delegation event by correlation_id. Returns True on success."""
        with self._lock:
            try:
                self._conn.execute(
                    """
                    INSERT INTO delegation_events (
                        correlation_id, session_id, tool_use_id, hook_name,
                        task_type, delegated_to, model_name,
                        quality_gate_passed, quality_gate_detail,
                        latency_ms, input_hash, input_redaction_policy,
                        contract_version, created_at
                    ) VALUES (
                        :correlation_id, :session_id, :tool_use_id, :hook_name,
                        :task_type, :delegated_to, :model_name,
                        :quality_gate_passed, :quality_gate_detail,
                        :latency_ms, :input_hash, :input_redaction_policy,
                        :contract_version, :created_at
                    )
                    ON CONFLICT(correlation_id) DO UPDATE SET
                        session_id              = excluded.session_id,
                        tool_use_id             = excluded.tool_use_id,
                        hook_name               = excluded.hook_name,
                        task_type               = excluded.task_type,
                        delegated_to            = excluded.delegated_to,
                        model_name              = excluded.model_name,
                        quality_gate_passed     = excluded.quality_gate_passed,
                        quality_gate_detail     = excluded.quality_gate_detail,
                        latency_ms              = excluded.latency_ms,
                        input_hash              = excluded.input_hash,
                        input_redaction_policy  = excluded.input_redaction_policy,
                        contract_version        = excluded.contract_version
                    """,
                    {
                        "correlation_id": event.correlation_id,
                        "session_id": event.session_id,
                        "tool_use_id": event.tool_use_id,
                        "hook_name": event.hook_name,
                        "task_type": event.task_type,
                        "delegated_to": event.delegated_to,
                        "model_name": event.model_name,
                        "quality_gate_passed": 1 if event.quality_gate_passed else 0,
                        "quality_gate_detail": event.quality_gate_detail,
                        "latency_ms": event.latency_ms,
                        "input_hash": event.input_hash,
                        "input_redaction_policy": event.input_redaction_policy,
                        "contract_version": event.contract_version,
                        "created_at": event.created_at,
                    },
                )
                self._conn.commit()
                return True
            except Exception:
                logger.exception(
                    "write_delegation_event failed for %s", event.correlation_id
                )
                self._conn.rollback()
                return False

    def write_llm_call_metric(self, metric: ModelLlmCallMetric) -> bool:
        """UPSERT an LLM call metric by input_hash. Returns True on success."""
        with self._lock:
            try:
                self._conn.execute(
                    """
                    INSERT INTO llm_call_metrics (
                        input_hash, model_id, prompt_tokens, completion_tokens,
                        estimated_cost_usd, usage_source, token_provenance, created_at
                    ) VALUES (
                        :input_hash, :model_id, :prompt_tokens, :completion_tokens,
                        :estimated_cost_usd, :usage_source, :token_provenance, :created_at
                    )
                    ON CONFLICT(input_hash) DO UPDATE SET
                        model_id            = excluded.model_id,
                        prompt_tokens       = excluded.prompt_tokens,
                        completion_tokens   = excluded.completion_tokens,
                        estimated_cost_usd  = excluded.estimated_cost_usd,
                        usage_source        = excluded.usage_source,
                        token_provenance    = excluded.token_provenance
                    """,
                    {
                        "input_hash": metric.input_hash,
                        "model_id": metric.model_id,
                        "prompt_tokens": metric.prompt_tokens,
                        "completion_tokens": metric.completion_tokens,
                        "estimated_cost_usd": metric.estimated_cost_usd,
                        "usage_source": metric.usage_source,
                        "token_provenance": metric.token_provenance,
                        "created_at": metric.created_at,
                    },
                )
                self._conn.commit()
                return True
            except Exception:
                logger.exception(
                    "write_llm_call_metric failed for hash %s", metric.input_hash
                )
                self._conn.rollback()
                return False

    def write_savings_estimate(self, estimate: ModelSavingsEstimate) -> bool:
        """UPSERT a savings estimate by composite key. Returns True on success."""
        with self._lock:
            try:
                self._conn.execute(
                    """
                    INSERT INTO savings_estimates (
                        session_id, event_timestamp, model_local, model_cloud_baseline,
                        local_cost_usd, cloud_cost_usd, savings_usd,
                        baseline_model, pricing_manifest_version, savings_method,
                        usage_source, created_at
                    ) VALUES (
                        :session_id, :event_timestamp, :model_local, :model_cloud_baseline,
                        :local_cost_usd, :cloud_cost_usd, :savings_usd,
                        :baseline_model, :pricing_manifest_version, :savings_method,
                        :usage_source, :created_at
                    )
                    ON CONFLICT(session_id, event_timestamp, model_local, model_cloud_baseline) DO UPDATE SET
                        local_cost_usd          = excluded.local_cost_usd,
                        cloud_cost_usd          = excluded.cloud_cost_usd,
                        savings_usd             = excluded.savings_usd,
                        baseline_model          = excluded.baseline_model,
                        pricing_manifest_version = excluded.pricing_manifest_version,
                        savings_method          = excluded.savings_method,
                        usage_source            = excluded.usage_source
                    """,
                    {
                        "session_id": estimate.session_id,
                        "event_timestamp": estimate.event_timestamp,
                        "model_local": estimate.model_local,
                        "model_cloud_baseline": estimate.model_cloud_baseline,
                        "local_cost_usd": estimate.local_cost_usd,
                        "cloud_cost_usd": estimate.cloud_cost_usd,
                        "savings_usd": estimate.savings_usd,
                        "baseline_model": estimate.baseline_model,
                        "pricing_manifest_version": estimate.pricing_manifest_version,
                        "savings_method": estimate.savings_method,
                        "usage_source": estimate.usage_source,
                        "created_at": estimate.created_at,
                    },
                )
                self._conn.commit()
                return True
            except Exception:
                logger.exception(
                    "write_savings_estimate failed for session %s", estimate.session_id
                )
                self._conn.rollback()
                return False

    def append_event_log(self, envelope: ModelEventLogEnvelope) -> bool:
        """Append-only insert of a raw envelope. Every call appends a new row."""
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO delegation_event_log (envelope, created_at) VALUES (?, ?)",
                    (envelope.payload, time.time()),
                )
                self._conn.commit()
                return True
            except Exception:
                logger.exception("append_event_log failed")
                self._conn.rollback()
                return False

    # ------------------------------------------------------------------
    # Read methods
    # ------------------------------------------------------------------

    def query_delegation_events(
        self,
        session_id: str | None = None,
        limit: int = 100,
    ) -> list[ModelDelegationEventRow]:
        """Return delegation events, optionally filtered by session_id."""
        with self._lock:
            if session_id is not None:
                rows = self._conn.execute(
                    "SELECT * FROM delegation_events WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
                    (session_id, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM delegation_events ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [ModelDelegationEventRow(**dict(r)) for r in rows]

    def query_savings_summary(
        self, session_id: str | None = None
    ) -> ModelSavingsSummary:
        """Return aggregate savings totals, optionally scoped to a session."""
        with self._lock:
            if session_id is not None:
                row = self._conn.execute(
                    """
                    SELECT
                        COUNT(*)            AS event_count,
                        SUM(local_cost_usd) AS total_local_cost_usd,
                        SUM(cloud_cost_usd) AS total_cloud_cost_usd,
                        SUM(savings_usd)    AS total_savings_usd
                    FROM savings_estimates
                    WHERE session_id = ?
                    """,
                    (session_id,),
                ).fetchone()
            else:
                row = self._conn.execute(
                    """
                    SELECT
                        COUNT(*)            AS event_count,
                        SUM(local_cost_usd) AS total_local_cost_usd,
                        SUM(cloud_cost_usd) AS total_cloud_cost_usd,
                        SUM(savings_usd)    AS total_savings_usd
                    FROM savings_estimates
                    """
                ).fetchone()
        if row is None:
            return ModelSavingsSummary()
        return ModelSavingsSummary(
            event_count=row["event_count"] or 0,
            total_local_cost_usd=row["total_local_cost_usd"] or 0.0,
            total_cloud_cost_usd=row["total_cloud_cost_usd"] or 0.0,
            total_savings_usd=row["total_savings_usd"] or 0.0,
        )

    def get_applied_migrations(self) -> list[str]:
        """Return list of applied migration versions in order."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT version FROM schema_migrations ORDER BY applied_at ASC"
            ).fetchall()
        return [r["version"] for r in rows]

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        with self._lock:
            self._conn.close()


__all__: list[str] = [
    "ModelDelegationEvent",
    "ModelDelegationEventRow",
    "ModelEventLogEnvelope",
    "ModelLlmCallMetric",
    "ModelSavingsEstimate",
    "ModelSavingsSummary",
    "SQLiteProjectionAdapter",
]
