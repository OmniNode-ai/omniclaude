# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Read-only client for the session_registry table in omnibase_infra Postgres.

Queries the session_registry table populated by the session registry projector.
Used exclusively by user-initiated skills (resume_session, set_session) -- not
in hot-path hook emission.

Doctrine D4 compliance:
    Resume queries return typed results (Found/NotFound/Unavailable).
    "No session history" and "registry unavailable" are never collapsed into None.

Connection:
    Reads OMNIBASE_INFRA_DB_URL from env. On connection failure, returns
    Unavailable(reason) -- never silently treats infra failure as absent history.

ARCHITECTURAL NOTE: Direct DB dependency from omniclaude to omnibase_infra
Postgres is acceptable because:
    1. Used only by user-initiated skills (not hot-path hooks)
    2. Skills already make network calls (Linear, GitHub APIs)
    3. Simple key lookups, not aggregations
    4. On failure: returns Unavailable(reason) explicitly (D4)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime

import psycopg2
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Read-only model for session registry rows
# ---------------------------------------------------------------------------


class ModelSessionRegistryRow(BaseModel):
    """Read-only projection of a session_registry Postgres row.

    This is a local read model -- the authoritative write model lives in
    omnibase_infra. Fields mirror the session_registry table columns
    returned by SELECT queries.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: str = Field(..., description="Linear ticket ID (e.g., 'OMN-1234').")
    status: str = Field(default="active", description="Current task status.")
    current_phase: str | None = Field(
        default=None, description="Current lifecycle phase."
    )
    worktree_path: str | None = Field(default=None, description="Git worktree path.")
    files_touched: list[str] = Field(
        default_factory=list, description="Files modified."
    )
    depends_on: list[str] = Field(
        default_factory=list, description="Dependency task_ids."
    )
    session_ids: list[str] = Field(default_factory=list, description="CLI session_ids.")
    correlation_ids: list[str] = Field(
        default_factory=list, description="Correlation UUIDs."
    )
    decisions: list[str] = Field(default_factory=list, description="Key decisions.")
    last_activity: datetime | None = Field(
        default=None, description="Most recent activity."
    )
    created_at: datetime | None = Field(
        default=None, description="Entry creation time."
    )


# ---------------------------------------------------------------------------
# D4: Typed lookup results -- Found / NotFound / Unavailable
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelSessionFound:
    """Session registry entry was found."""

    entry: ModelSessionRegistryRow


@dataclass(frozen=True)
class ModelSessionNotFound:
    """No session history exists for the requested task_id."""

    task_id: str


@dataclass(frozen=True)
class ModelRegistryUnavailable:
    """Session registry is unreachable or errored."""

    reason: str


ModelSessionLookupResult = (
    ModelSessionFound | ModelSessionNotFound | ModelRegistryUnavailable
)

# ---------------------------------------------------------------------------
# SQL queries (read-only)
# ---------------------------------------------------------------------------

_SELECT_BY_TASK_ID = """\
SELECT task_id, status, current_phase, worktree_path,
       files_touched, depends_on, session_ids, correlation_ids, decisions,
       last_activity, created_at
FROM session_registry
WHERE task_id = %s
"""

_SELECT_ACTIVE = """\
SELECT task_id, status, current_phase, worktree_path,
       files_touched, depends_on, session_ids, correlation_ids, decisions,
       last_activity, created_at
FROM session_registry
WHERE status = 'active'
ORDER BY last_activity DESC NULLS LAST
"""

# Column names returned by SELECT queries (must match SQL column order)
_COLUMNS = (
    "task_id",
    "status",
    "current_phase",
    "worktree_path",
    "files_touched",
    "depends_on",
    "session_ids",
    "correlation_ids",
    "decisions",
    "last_activity",
    "created_at",
)


def _row_to_model(row: tuple[object, ...]) -> ModelSessionRegistryRow:
    """Convert a psycopg2 row tuple to a ModelSessionRegistryRow."""
    raw = dict(zip(_COLUMNS, row, strict=True))
    # Normalize Postgres arrays to Python lists
    for key in (
        "files_touched",
        "depends_on",
        "session_ids",
        "correlation_ids",
        "decisions",
    ):
        val = raw.get(key)
        raw[key] = list(val) if val is not None else []
    return ModelSessionRegistryRow.model_validate(raw)


class SessionRegistryClient:
    """Synchronous read-only client for the session_registry Postgres table.

    Parameters
    ----------
    db_url:
        PostgreSQL connection string. If ``None``, reads ``OMNIBASE_INFRA_DB_URL``
        from the environment. Passing ``None`` with no env var set will cause
        connection methods to return ``ModelRegistryUnavailable``.
    """

    def __init__(self, db_url: str | None = None) -> None:
        self._db_url = db_url or os.environ.get("OMNIBASE_INFRA_DB_URL")

    def _connect(self) -> psycopg2.extensions.connection:
        """Create a psycopg2 connection. Returns connection or raises."""
        if not self._db_url:
            msg = "OMNIBASE_INFRA_DB_URL not set and no db_url provided"
            raise ConnectionError(msg)
        return psycopg2.connect(self._db_url)

    def get_session(self, task_id: str) -> ModelSessionLookupResult:
        """Look up a session registry entry by task_id.

        Returns:
            ModelSessionFound if entry exists.
            ModelSessionNotFound if no entry for this task_id.
            ModelRegistryUnavailable on connection/query failure.
        """
        try:
            conn = self._connect()
        except (ConnectionError, psycopg2.Error, OSError) as exc:
            logger.warning(
                "session_registry_unavailable",
                extra={"error": str(exc)},
            )
            return ModelRegistryUnavailable(reason=str(exc))

        try:
            with conn.cursor() as cur:
                cur.execute(_SELECT_BY_TASK_ID, (task_id,))
                row = cur.fetchone()
                if row is None:
                    return ModelSessionNotFound(task_id=task_id)
                return ModelSessionFound(entry=_row_to_model(row))
        except (psycopg2.Error, OSError) as exc:
            logger.warning(
                "session_registry_query_failed",
                extra={"task_id": task_id, "error": str(exc)},
            )
            return ModelRegistryUnavailable(reason=str(exc))
        finally:
            conn.close()

    def list_active_sessions(
        self,
    ) -> list[ModelSessionRegistryRow] | ModelRegistryUnavailable:
        """List all active session registry entries.

        Returns:
            List of ModelSessionRegistryRow on success.
            ModelRegistryUnavailable on connection/query failure.
        """
        try:
            conn = self._connect()
        except (ConnectionError, psycopg2.Error, OSError) as exc:
            logger.warning(
                "session_registry_unavailable",
                extra={"error": str(exc)},
            )
            return ModelRegistryUnavailable(reason=str(exc))

        try:
            with conn.cursor() as cur:
                cur.execute(_SELECT_ACTIVE)
                rows = cur.fetchall()
                return [_row_to_model(row) for row in rows]
        except (psycopg2.Error, OSError) as exc:
            logger.warning(
                "session_registry_list_failed",
                extra={"error": str(exc)},
            )
            return ModelRegistryUnavailable(reason=str(exc))
        finally:
            conn.close()

    @staticmethod
    def format_resume_context(entry: ModelSessionRegistryRow) -> str:
        """Format a registry entry into a human-readable resume context string.

        Used by the resume_session skill to display session state to the user.

        Args:
            entry: A session registry row (from get_session().entry).

        Returns:
            Multi-line string summarizing the session state.
        """
        lines: list[str] = []
        lines.append(f"## Session Resume: {entry.task_id}")
        lines.append("")
        lines.append(f"**Status:** {entry.status}")
        lines.append(f"**Phase:** {entry.current_phase or 'unknown'}")

        if entry.last_activity is not None:
            lines.append(f"**Last Activity:** {entry.last_activity.isoformat()}")

        lines.append(f"**Sessions:** {len(entry.session_ids)} session(s)")

        if entry.files_touched:
            lines.append("")
            lines.append("**Files Touched:**")
            for f in entry.files_touched:
                lines.append(f"- `{f}`")

        if entry.depends_on:
            lines.append("")
            lines.append("**Dependencies:**")
            for dep in entry.depends_on:
                lines.append(f"- {dep}")

        if entry.decisions:
            lines.append("")
            lines.append("**Decisions:**")
            for dec in entry.decisions:
                lines.append(f"- {dec}")

        return "\n".join(lines)
