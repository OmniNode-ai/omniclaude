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
from typing import Any

import psycopg2

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# D4: Typed lookup results -- Found / NotFound / Unavailable
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelSessionFound:
    """Session registry entry was found."""

    entry: dict[str, Any]


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

    @staticmethod
    def _row_to_dict(row: tuple[Any, ...], description: Any) -> dict[str, Any]:
        """Convert a psycopg2 row + cursor.description to a dict."""
        columns = [col.name for col in description]
        return dict(zip(columns, row, strict=True))

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
                entry = self._row_to_dict(row, cur.description)
                # Normalize Postgres arrays to Python lists
                for key in (
                    "files_touched",
                    "depends_on",
                    "session_ids",
                    "correlation_ids",
                    "decisions",
                ):
                    if entry.get(key) is not None:
                        entry[key] = list(entry[key])
                    else:
                        entry[key] = []
                return ModelSessionFound(entry=entry)
        except (psycopg2.Error, OSError) as exc:
            logger.warning(
                "session_registry_query_failed",
                extra={"task_id": task_id, "error": str(exc)},
            )
            return ModelRegistryUnavailable(reason=str(exc))
        finally:
            conn.close()

    def list_active_sessions(self) -> list[dict[str, Any]] | ModelRegistryUnavailable:
        """List all active session registry entries.

        Returns:
            List of entry dicts on success.
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
                entries = []
                for row in rows:
                    entry = self._row_to_dict(row, cur.description)
                    for key in (
                        "files_touched",
                        "depends_on",
                        "session_ids",
                        "correlation_ids",
                        "decisions",
                    ):
                        if entry.get(key) is not None:
                            entry[key] = list(entry[key])
                        else:
                            entry[key] = []
                    entries.append(entry)
                return entries
        except (psycopg2.Error, OSError) as exc:
            logger.warning(
                "session_registry_list_failed",
                extra={"error": str(exc)},
            )
            return ModelRegistryUnavailable(reason=str(exc))
        finally:
            conn.close()

    @staticmethod
    def format_resume_context(entry: dict[str, Any]) -> str:
        """Format a registry entry into a human-readable resume context string.

        Used by the resume_session skill to display session state to the user.

        Args:
            entry: A session registry entry dict (from get_session().entry).

        Returns:
            Multi-line string summarizing the session state.
        """
        task_id = entry.get("task_id", "unknown")
        status = entry.get("status", "unknown")
        phase = entry.get("current_phase", "unknown")
        files = entry.get("files_touched", [])
        depends = entry.get("depends_on", [])
        decisions = entry.get("decisions", [])
        sessions = entry.get("session_ids", [])
        last_activity = entry.get("last_activity")

        lines: list[str] = []
        lines.append(f"## Session Resume: {task_id}")
        lines.append("")
        lines.append(f"**Status:** {status}")
        lines.append(f"**Phase:** {phase}")

        if last_activity:
            if isinstance(last_activity, datetime):
                lines.append(f"**Last Activity:** {last_activity.isoformat()}")
            else:
                lines.append(f"**Last Activity:** {last_activity}")

        lines.append(f"**Sessions:** {len(sessions)} session(s)")

        if files:
            lines.append("")
            lines.append("**Files Touched:**")
            for f in files:
                lines.append(f"- `{f}`")

        if depends:
            lines.append("")
            lines.append("**Dependencies:**")
            for dep in depends:
                lines.append(f"- {dep}")

        if decisions:
            lines.append("")
            lines.append("**Decisions:**")
            for dec in decisions:
                lines.append(f"- {dec}")

        return "\n".join(lines)
