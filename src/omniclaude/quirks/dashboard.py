# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""NodeQuirkDashboardQueryEffect -- ONEX Effect Node.

Read-side query API over the ``quirk_signals`` and ``quirk_findings`` tables.

Provides structured query helpers for the QuirkDashboard (omnidash integration)
and any other consumer that needs aggregated quirk data without re-running
the full detection pipeline.

All queries are **read-only** and return plain dicts suitable for JSON
serialisation.  When no DB session factory is configured (e.g. unit tests)
every method returns empty/zero results gracefully.

Node type: Effect  (external I/O -- read-only DB queries)
Node name: NodeQuirkDashboardQueryEffect

Related:
    - OMN-2533: DB schema (quirk_signals + quirk_findings tables)
    - OMN-2556: Extractor + classifier write to these tables
    - OMN-2586: This ticket -- read-side dashboard API
    - OMN-2360: Quirks Detector epic
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response models (plain dataclasses -- no Pydantic dependency for read-side)
# ---------------------------------------------------------------------------


class QuirkSignalRow:
    """Lightweight view of a ``quirk_signals`` row.

    Attributes:
        id: UUID string.
        quirk_type: QuirkType enum value (e.g. ``"STUB_CODE"``).
        session_id: Session identifier.
        confidence: Detection confidence [0.0, 1.0].
        evidence: List of evidence strings.
        stage: Policy enforcement stage (``"OBSERVE"``, ``"WARN"``, ``"BLOCK"``).
        detected_at: ISO-8601 timestamp string.
        extraction_method: Detection method.
        file_path: Optional file path.
        diff_hunk: Optional diff fragment.
        ast_span: Optional ``[start_line, end_line]`` pair.
        created_at: ISO-8601 row creation timestamp.
    """

    __slots__ = (
        "ast_span",
        "confidence",
        "created_at",
        "detected_at",
        "diff_hunk",
        "evidence",
        "extraction_method",
        "file_path",
        "id",
        "quirk_type",
        "session_id",
        "stage",
    )

    def __init__(self, row: Any) -> None:
        self.id = str(row[0])
        self.quirk_type = str(row[1])
        self.session_id = str(row[2])
        self.confidence = float(row[3])
        self.evidence = list(row[4]) if row[4] else []
        self.stage = str(row[5])
        self.detected_at = row[6].isoformat() if hasattr(row[6], "isoformat") else str(row[6])
        self.extraction_method = str(row[7])
        self.file_path = str(row[8]) if row[8] is not None else None
        self.diff_hunk = str(row[9]) if row[9] is not None else None
        self.ast_span = list(row[10]) if row[10] is not None else None
        self.created_at = row[11].isoformat() if hasattr(row[11], "isoformat") else str(row[11])

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-safe dict."""
        return {
            "id": self.id,
            "quirk_type": self.quirk_type,
            "session_id": self.session_id,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "stage": self.stage,
            "detected_at": self.detected_at,
            "extraction_method": self.extraction_method,
            "file_path": self.file_path,
            "diff_hunk": self.diff_hunk,
            "ast_span": self.ast_span,
            "created_at": self.created_at,
        }


class QuirkFindingRow:
    """Lightweight view of a ``quirk_findings`` row.

    Attributes:
        id: UUID string.
        signal_id: Foreign-key reference to the originating signal.
        quirk_type: QuirkType enum value.
        policy_recommendation: ``"observe"``, ``"warn"``, or ``"block"``.
        validator_blueprint_id: Optional validator blueprint ID.
        suggested_exemptions: List of exemption strings.
        fix_guidance: Human-readable fix guidance.
        confidence: Policy confidence [0.0, 1.0].
        created_at: ISO-8601 row creation timestamp.
    """

    __slots__ = (
        "confidence",
        "created_at",
        "fix_guidance",
        "id",
        "policy_recommendation",
        "quirk_type",
        "signal_id",
        "suggested_exemptions",
        "validator_blueprint_id",
    )

    def __init__(self, row: Any) -> None:
        self.id = str(row[0])
        self.signal_id = str(row[1])
        self.quirk_type = str(row[2])
        self.policy_recommendation = str(row[3])
        self.validator_blueprint_id = str(row[4]) if row[4] is not None else None
        self.suggested_exemptions = list(row[5]) if row[5] else []
        self.fix_guidance = str(row[6])
        self.confidence = float(row[7])
        self.created_at = row[8].isoformat() if hasattr(row[8], "isoformat") else str(row[8])

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-safe dict."""
        return {
            "id": self.id,
            "signal_id": self.signal_id,
            "quirk_type": self.quirk_type,
            "policy_recommendation": self.policy_recommendation,
            "validator_blueprint_id": self.validator_blueprint_id,
            "suggested_exemptions": self.suggested_exemptions,
            "fix_guidance": self.fix_guidance,
            "confidence": self.confidence,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# NodeQuirkDashboardQueryEffect
# ---------------------------------------------------------------------------


class NodeQuirkDashboardQueryEffect:
    """ONEX Effect Node providing read-side query access to quirk tables.

    All public methods are ``async`` and accept keyword-only filter arguments.
    When ``db_session_factory`` is ``None`` every method returns an empty
    result without raising (useful for unit tests and offline environments).

    Usage::

        query = NodeQuirkDashboardQueryEffect(db_session_factory=factory)

        # Count signals per quirk type in last 7 days
        summary = await query.summary()

        # Recent signals for one session
        rows = await query.list_signals(session_id="abc", limit=20)

        # Findings at warn+ level
        findings = await query.list_findings(
            policy_recommendation="warn", limit=50
        )
    """

    def __init__(self, db_session_factory: Any | None = None) -> None:
        """Initialise the dashboard query node.

        Args:
            db_session_factory: Async SQLAlchemy session factory (``async_sessionmaker``
                or similar).  When ``None``, all queries return empty results.
        """
        self._db_session_factory = db_session_factory

    # ------------------------------------------------------------------
    # Summary / aggregation
    # ------------------------------------------------------------------

    async def summary(self, days: int = 7) -> dict[str, Any]:
        """Return aggregated quirk statistics for the last *days* days.

        Result shape::

            {
                "window_days": 7,
                "total_signals": 142,
                "total_findings": 12,
                "by_quirk_type": {
                    "STUB_CODE": {"signals": 45, "findings": 4,
                                  "latest_recommendation": "warn"},
                    ...
                },
                "by_stage": {"OBSERVE": 100, "WARN": 40, "BLOCK": 2},
                "by_recommendation": {"observe": 8, "warn": 3, "block": 1},
            }

        Args:
            days: Lookback window in days (default 7).

        Returns:
            Aggregation dict.  All counts are 0 when DB is unavailable.
        """
        if self._db_session_factory is None:
            return _empty_summary(days)

        try:
            import importlib

            sa = importlib.import_module("sqlalchemy")
            sa_text = sa.text

            async with self._db_session_factory() as session:
                signal_rows = (
                    await session.execute(
                        sa_text(_SIGNALS_BY_TYPE_SQL), {"days": days}
                    )
                ).fetchall()

                finding_rows = (
                    await session.execute(
                        sa_text(_FINDINGS_BY_TYPE_SQL), {"days": days}
                    )
                ).fetchall()

                stage_rows = (
                    await session.execute(
                        sa_text(_SIGNALS_BY_STAGE_SQL), {"days": days}
                    )
                ).fetchall()

                rec_rows = (
                    await session.execute(
                        sa_text(_FINDINGS_BY_RECOMMENDATION_SQL), {"days": days}
                    )
                ).fetchall()

            return _build_summary(days, signal_rows, finding_rows, stage_rows, rec_rows)

        except Exception:
            logger.exception("NodeQuirkDashboardQueryEffect: summary query failed")
            return _empty_summary(days)

    # ------------------------------------------------------------------
    # Signal listing
    # ------------------------------------------------------------------

    async def list_signals(
        self,
        *,
        quirk_type: str | None = None,
        session_id: str | None = None,
        stage: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List ``quirk_signals`` rows with optional filters.

        Args:
            quirk_type: Filter to a specific quirk type (e.g. ``"STUB_CODE"``).
            session_id: Filter to a specific session.
            stage: Filter to a specific enforcement stage.
            limit: Maximum rows to return (capped at 1000).
            offset: Row offset for pagination.

        Returns:
            List of signal dicts (newest first).  Empty list on DB unavailability.
        """
        if self._db_session_factory is None:
            return []

        limit = min(limit, 1000)

        try:
            import importlib

            sa = importlib.import_module("sqlalchemy")
            sa_text = sa.text

            params: dict[str, Any] = {"limit": limit, "offset": offset}
            where_clauses: list[str] = []

            if quirk_type is not None:
                where_clauses.append("quirk_type = :quirk_type")
                params["quirk_type"] = quirk_type
            if session_id is not None:
                where_clauses.append("session_id = :session_id")
                params["session_id"] = session_id
            if stage is not None:
                where_clauses.append("stage = :stage")
                params["stage"] = stage

            where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
            sql = f"""
                SELECT id, quirk_type, session_id, confidence, evidence, stage,
                       detected_at, extraction_method, file_path, diff_hunk,
                       ast_span, created_at
                FROM quirk_signals
                {where_sql}
                ORDER BY detected_at DESC
                LIMIT :limit OFFSET :offset
            """
            async with self._db_session_factory() as session:
                rows = (await session.execute(sa_text(sql), params)).fetchall()

            return [QuirkSignalRow(r).to_dict() for r in rows]

        except Exception:
            logger.exception("NodeQuirkDashboardQueryEffect: list_signals query failed")
            return []

    # ------------------------------------------------------------------
    # Finding listing
    # ------------------------------------------------------------------

    async def list_findings(
        self,
        *,
        quirk_type: str | None = None,
        policy_recommendation: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List ``quirk_findings`` rows with optional filters.

        Args:
            quirk_type: Filter to a specific quirk type.
            policy_recommendation: Filter to ``"observe"``, ``"warn"``, or ``"block"``.
            limit: Maximum rows to return (capped at 1000).
            offset: Row offset for pagination.

        Returns:
            List of finding dicts (newest first).  Empty list on DB unavailability.
        """
        if self._db_session_factory is None:
            return []

        limit = min(limit, 1000)

        try:
            import importlib

            sa = importlib.import_module("sqlalchemy")
            sa_text = sa.text

            params: dict[str, Any] = {"limit": limit, "offset": offset}
            where_clauses: list[str] = []

            if quirk_type is not None:
                where_clauses.append("quirk_type = :quirk_type")
                params["quirk_type"] = quirk_type
            if policy_recommendation is not None:
                where_clauses.append("policy_recommendation = :policy_recommendation")
                params["policy_recommendation"] = policy_recommendation

            where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
            sql = f"""
                SELECT id, signal_id, quirk_type, policy_recommendation,
                       validator_blueprint_id, suggested_exemptions,
                       fix_guidance, confidence, created_at
                FROM quirk_findings
                {where_sql}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """
            async with self._db_session_factory() as session:
                rows = (await session.execute(sa_text(sql), params)).fetchall()

            return [QuirkFindingRow(r).to_dict() for r in rows]

        except Exception:
            logger.exception("NodeQuirkDashboardQueryEffect: list_findings query failed")
            return []

    # ------------------------------------------------------------------
    # Single-row lookups
    # ------------------------------------------------------------------

    async def get_signal(self, signal_id: str) -> dict[str, Any] | None:
        """Fetch a single ``quirk_signals`` row by ID.

        Args:
            signal_id: UUID string of the signal.

        Returns:
            Signal dict, or ``None`` if not found.
        """
        if self._db_session_factory is None:
            return None

        try:
            import importlib

            sa = importlib.import_module("sqlalchemy")
            sa_text = sa.text

            async with self._db_session_factory() as session:
                row = (
                    await session.execute(
                        sa_text(_GET_SIGNAL_SQL), {"id": signal_id}
                    )
                ).fetchone()

            return QuirkSignalRow(row).to_dict() if row else None

        except Exception:
            logger.exception(
                "NodeQuirkDashboardQueryEffect: get_signal failed (id=%s)", signal_id
            )
            return None

    async def get_finding(self, finding_id: str) -> dict[str, Any] | None:
        """Fetch a single ``quirk_findings`` row by ID.

        Args:
            finding_id: UUID string of the finding.

        Returns:
            Finding dict, or ``None`` if not found.
        """
        if self._db_session_factory is None:
            return None

        try:
            import importlib

            sa = importlib.import_module("sqlalchemy")
            sa_text = sa.text

            async with self._db_session_factory() as session:
                row = (
                    await session.execute(
                        sa_text(_GET_FINDING_SQL), {"id": finding_id}
                    )
                ).fetchone()

            return QuirkFindingRow(row).to_dict() if row else None

        except Exception:
            logger.exception(
                "NodeQuirkDashboardQueryEffect: get_finding failed (id=%s)", finding_id
            )
            return None


# ---------------------------------------------------------------------------
# SQL strings
# ---------------------------------------------------------------------------

_SIGNALS_BY_TYPE_SQL = """
    SELECT quirk_type, COUNT(*) AS signal_count
    FROM quirk_signals
    WHERE detected_at >= NOW() - INTERVAL ':days days'
    GROUP BY quirk_type
    ORDER BY signal_count DESC
"""

_FINDINGS_BY_TYPE_SQL = """
    SELECT f.quirk_type, COUNT(*) AS finding_count,
           MAX(f.policy_recommendation) AS latest_recommendation
    FROM quirk_findings f
    JOIN quirk_signals s ON s.id = f.signal_id
    WHERE s.detected_at >= NOW() - INTERVAL ':days days'
    GROUP BY f.quirk_type
    ORDER BY finding_count DESC
"""

_SIGNALS_BY_STAGE_SQL = """
    SELECT stage, COUNT(*) AS cnt
    FROM quirk_signals
    WHERE detected_at >= NOW() - INTERVAL ':days days'
    GROUP BY stage
"""

_FINDINGS_BY_RECOMMENDATION_SQL = """
    SELECT policy_recommendation, COUNT(*) AS cnt
    FROM quirk_findings f
    JOIN quirk_signals s ON s.id = f.signal_id
    WHERE s.detected_at >= NOW() - INTERVAL ':days days'
    GROUP BY policy_recommendation
"""

_GET_SIGNAL_SQL = """
    SELECT id, quirk_type, session_id, confidence, evidence, stage,
           detected_at, extraction_method, file_path, diff_hunk,
           ast_span, created_at
    FROM quirk_signals
    WHERE id = :id
"""

_GET_FINDING_SQL = """
    SELECT id, signal_id, quirk_type, policy_recommendation,
           validator_blueprint_id, suggested_exemptions,
           fix_guidance, confidence, created_at
    FROM quirk_findings
    WHERE id = :id
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _empty_summary(days: int) -> dict[str, Any]:
    """Return an empty summary structure for when DB is unavailable."""
    return {
        "window_days": days,
        "total_signals": 0,
        "total_findings": 0,
        "by_quirk_type": {},
        "by_stage": {},
        "by_recommendation": {},
    }


def _build_summary(
    days: int,
    signal_rows: list[Any],
    finding_rows: list[Any],
    stage_rows: list[Any],
    rec_rows: list[Any],
) -> dict[str, Any]:
    """Assemble summary dict from raw query result rows."""
    by_quirk_type: dict[str, dict[str, Any]] = {}

    for row in signal_rows:
        qt = str(row[0])
        by_quirk_type.setdefault(qt, {"signals": 0, "findings": 0, "latest_recommendation": None})
        by_quirk_type[qt]["signals"] = int(row[1])

    for row in finding_rows:
        qt = str(row[0])
        by_quirk_type.setdefault(qt, {"signals": 0, "findings": 0, "latest_recommendation": None})
        by_quirk_type[qt]["findings"] = int(row[1])
        by_quirk_type[qt]["latest_recommendation"] = str(row[2]) if row[2] else None

    total_signals = sum(v["signals"] for v in by_quirk_type.values())
    total_findings = sum(v["findings"] for v in by_quirk_type.values())

    by_stage = {str(r[0]): int(r[1]) for r in stage_rows}
    by_recommendation = {str(r[0]): int(r[1]) for r in rec_rows}

    return {
        "window_days": days,
        "total_signals": total_signals,
        "total_findings": total_findings,
        "by_quirk_type": by_quirk_type,
        "by_stage": by_stage,
        "by_recommendation": by_recommendation,
    }


__all__ = [
    "NodeQuirkDashboardQueryEffect",
    "QuirkFindingRow",
    "QuirkSignalRow",
]
