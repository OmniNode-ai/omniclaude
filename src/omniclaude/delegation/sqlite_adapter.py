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

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_MIGRATION_SQL = _MIGRATIONS_DIR / "001_create_delegation_tables.sql"
_MIGRATION_002_SQL = _MIGRATIONS_DIR / "002_align_with_projection_handler.sql"
_DEFAULT_DB_PATH = Path.home() / ".omninode" / "delegation" / "delegation.sqlite"
_MIGRATION_VERSION = "002"
_MIGRATION_DESCRIPTION = "Align with projection handler schema"


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
    timestamp: str | None = None
    delegated_by: str = ""
    quality_gates_checked: int = 0
    quality_gates_failed: int = 0
    delegation_latency_ms: int | None = None
    repo: str | None = None
    is_shadow: int = 0
    llm_call_id: str | None = None
    tokens_input: int = 0
    tokens_output: int = 0
    cost_savings_usd: float = 0.0


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
    The connection lifecycle is owned by the caller — inject via DI or use
    ``make_adapter()`` for the standard on-disk path.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        conn.row_factory = sqlite3.Row
        self._conn = conn
        self._lock = threading.Lock()
        self._apply_migrations()

    # ------------------------------------------------------------------
    # Migration
    # ------------------------------------------------------------------

    def _apply_migrations(self) -> None:
        with self._lock:
            self._conn.executescript(_MIGRATION_SQL.read_text())
            self._conn.execute(
                "INSERT OR IGNORE INTO schema_migrations (version, applied_at, description) VALUES (?, ?, ?)",
                ("001", time.time(), "Create delegation projection tables"),
            )
            applied = {
                r[0]
                for r in self._conn.execute(
                    "SELECT version FROM schema_migrations"
                ).fetchall()
            }
            if "002" not in applied:
                migration_sql = "\n".join(
                    line
                    for line in _MIGRATION_002_SQL.read_text().splitlines()
                    if not line.lstrip().startswith("--")
                )
                for stmt in migration_sql.strip().split(";"):
                    stmt = stmt.strip()
                    if not stmt:
                        continue
                    try:
                        self._conn.execute(stmt)
                    except sqlite3.OperationalError as exc:
                        if "duplicate column" not in str(exc):
                            raise
                self._conn.execute(
                    "INSERT OR IGNORE INTO schema_migrations (version, applied_at, description) VALUES (?, ?, ?)",
                    ("002", time.time(), _MIGRATION_DESCRIPTION),
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

    # ------------------------------------------------------------------
    # ProtocolProjectionDatabaseSync — generic upsert/query
    # ------------------------------------------------------------------

    # Maps from the projection handler's row field names to the SQLite column names.
    # Fields present in handler row but absent from the SQLite schema are dropped.
    _DELEGATION_EVENTS_COLUMNS: frozenset[str] = frozenset(
        {
            "correlation_id",
            "session_id",
            "tool_use_id",
            "hook_name",
            "task_type",
            "delegated_to",
            "model_name",
            "quality_gate_passed",
            "quality_gate_detail",
            "latency_ms",
            "input_hash",
            "input_redaction_policy",
            "contract_version",
            "created_at",
        }
    )

    def upsert(
        self,
        table: str,
        conflict_key: str,
        row: dict[str, object],
    ) -> bool:
        """Generic UPSERT implementing ProtocolProjectionDatabaseSync.

        Only `delegation_events` is supported; other tables return False.
        Extra fields not present in the SQLite schema are silently dropped.
        Fields absent from the schema but present in the row (e.g.
        `delegated_by`, `timestamp`, `quality_gates_*`, `delegation_latency_ms`,
        `repo`, `is_shadow`, `llm_call_id`) are mapped where possible:
          - delegation_latency_ms → latency_ms
        """
        if table != "delegation_events":
            logger.warning("upsert() called for unsupported table %r — skipping", table)
            return False

        if conflict_key not in self._DELEGATION_EVENTS_COLUMNS:
            logger.warning(
                "upsert() called with invalid conflict_key %r for table %r — skipping",
                conflict_key,
                table,
            )
            return False

        # Map handler field names → SQLite column names.
        mapped: dict[str, object] = dict(row)
        if "delegation_latency_ms" in mapped and "latency_ms" not in mapped:
            mapped["latency_ms"] = mapped.pop("delegation_latency_ms")
        else:
            mapped.pop("delegation_latency_ms", None)

        # Drop fields absent from the SQLite schema.
        filtered = {
            k: v for k, v in mapped.items() if k in self._DELEGATION_EVENTS_COLUMNS
        }

        # Ensure required fields have defaults.
        filtered.setdefault("task_type", "")
        filtered.setdefault("delegated_to", "")
        filtered.setdefault("model_name", "")
        filtered.setdefault("quality_gate_passed", False)
        filtered.setdefault("input_redaction_policy", "hash_only")
        filtered.setdefault("contract_version", "v1")
        filtered.setdefault("created_at", time.time())

        if "quality_gate_passed" in filtered:
            filtered["quality_gate_passed"] = (
                1 if filtered["quality_gate_passed"] else 0
            )

        cols = list(filtered.keys())
        placeholders = ", ".join(f":{c}" for c in cols)
        update_set = ", ".join(f"{c} = excluded.{c}" for c in cols if c != conflict_key)
        col_list = ", ".join(cols)
        sql = (
            f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "  # noqa: S608  # nosec B608
            f"ON CONFLICT({conflict_key}) DO UPDATE SET {update_set}"
        )

        with self._lock:
            try:
                self._conn.execute(sql, filtered)
                self._conn.commit()
                return True
            except Exception:
                logger.exception(
                    "upsert() failed for table=%r conflict_key=%r correlation_id=%r",
                    table,
                    conflict_key,
                    filtered.get("correlation_id"),
                )
                self._conn.rollback()
                return False

    _ALLOWED_QUERY_TABLES: frozenset[str] = frozenset({"delegation_events"})

    def query(
        self,
        table: str,
        filters: dict[str, object] | None = None,
    ) -> list[dict[str, object]]:
        """Generic query implementing ProtocolProjectionDatabaseSync."""
        if table not in self._ALLOWED_QUERY_TABLES:
            logger.warning("query() called for unsupported table %r — skipping", table)
            return []
        if filters:
            invalid_keys = [
                k for k in filters if k not in self._DELEGATION_EVENTS_COLUMNS
            ]
            if invalid_keys:
                logger.warning(
                    "query() called with invalid filter keys %r for table %r — skipping",
                    invalid_keys,
                    table,
                )
                return []
        with self._lock:
            try:
                if filters:
                    where_clause = " AND ".join(f"{k} = ?" for k in filters)
                    values = list(filters.values())
                    rows = self._conn.execute(
                        f"SELECT * FROM {table} WHERE {where_clause}",  # noqa: S608  # nosec B608
                        values,
                    ).fetchall()
                else:
                    rows = self._conn.execute(
                        f"SELECT * FROM {table}",  # noqa: S608  # nosec B608
                    ).fetchall()
                return [dict(r) for r in rows]
            except Exception:
                logger.exception(
                    "query() failed for table=%r filters=%r", table, filters
                )
                return []

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        with self._lock:
            self._conn.close()


def make_adapter(db_path: Path | None = None) -> SQLiteProjectionAdapter:
    """Create a ``SQLiteProjectionAdapter`` backed by an on-disk (or in-memory) file.

    This is the authorised call site for ``sqlite3.connect()`` — callers that need
    the standard customer-deployable path use this factory; code under test passes
    ``sqlite3.connect(":memory:")`` directly to the constructor.
    """
    resolved = db_path or _DEFAULT_DB_PATH
    resolved.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(resolved), check_same_thread=False)  # di-ok
    return SQLiteProjectionAdapter(conn)


__all__: list[str] = [
    "ModelDelegationEvent",
    "ModelDelegationEventRow",
    "ModelEventLogEnvelope",
    "ModelLlmCallMetric",
    "ModelSavingsEstimate",
    "ModelSavingsSummary",
    "SQLiteProjectionAdapter",
    "make_adapter",
]
