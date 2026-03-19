# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
Skill Usage Logger — OMN-3454

Appends a structured JSON line to ~/.claude/onex-skill-usage.log whenever the
PostToolUse hook fires for a ``Skill`` tool invocation.  Optionally writes to a
``skill_usage`` PostgreSQL table when ``ENABLE_POSTGRES=true`` and the DB is
reachable.

Privacy guarantee: the log contains only skill_name, timestamp, and session_id.
No prompt content, file paths, or code fragments are written.

Callers must treat this module as fire-and-forget; it never raises.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

DEFAULT_USAGE_LOG: Path = Path.home() / ".claude" / "onex-skill-usage.log"

_VALID_STATUSES = frozenset({"success", "failed", "partial"})

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def append_skill_usage(
    skill_name: str,
    session_id: str,
    *,
    log_path: Path | None = None,
    db_enabled: bool | None = None,
) -> bool:
    """Append one JSON line to the skill usage log.

    Parameters
    ----------
    skill_name:
        Fully-qualified skill identifier, e.g. ``onex:ticket-pipeline``.
    session_id:
        Claude session identifier extracted from the hook payload.
    log_path:
        Override the default log path (``~/.claude/onex-skill-usage.log``).
        Primarily used in tests.
    db_enabled:
        Override ``ENABLE_POSTGRES`` env-var detection.  ``None`` means read
        from the environment.

    Returns
    -------
    bool
        ``True`` when the file write succeeded; ``False`` on any failure.
        DB failures are always non-fatal and do not affect the return value.
    """
    if not skill_name:
        return False

    entry = _build_entry(skill_name=skill_name, session_id=session_id)
    file_ok = _write_to_file(entry=entry, log_path=log_path or DEFAULT_USAGE_LOG)

    # Optional Postgres write — always non-fatal
    _maybe_write_to_db(entry=entry, db_enabled=db_enabled)

    return file_ok


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_entry(*, skill_name: str, session_id: str) -> dict[str, Any]:
    """Build a log entry dict with only privacy-safe fields."""
    return {
        "skill_name": skill_name,
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "session_id": session_id,
    }


def _write_to_file(*, entry: dict[str, Any], log_path: Path) -> bool:
    """Append *entry* as a JSON line to *log_path*.  Never raises."""
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, separators=(",", ":")) + "\n"
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(line)
        return True
    except Exception:  # noqa: BLE001
        return False


def _maybe_write_to_db(
    *,
    entry: dict[str, Any],
    db_enabled: bool | None,
) -> None:
    """Optionally insert *entry* into ``skill_usage`` table.  Never raises."""
    if db_enabled is None:
        db_enabled = os.getenv(  # ONEX_FLAG_EXEMPT: migration
            "ENABLE_POSTGRES", ""
        ).lower() in {"1", "true", "yes"}

    if not db_enabled:
        return

    try:
        _write_to_db(entry)
    except Exception:  # noqa: BLE001  # nosec B110 - hook must not block
        pass


def _write_to_db(entry: dict[str, Any]) -> None:
    """Insert *entry* into the ``skill_usage`` table.

    Schema (created once via migration or CREATE TABLE IF NOT EXISTS):

        CREATE TABLE skill_usage (
            id         SERIAL PRIMARY KEY,
            skill_name TEXT        NOT NULL,
            session_id TEXT        NOT NULL,
            invoked_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX ON skill_usage(skill_name);
        CREATE INDEX ON skill_usage(session_id);

    Raises on any DB error so the caller (``_maybe_write_to_db``) can swallow it.
    """
    import psycopg2

    db_url = os.getenv(
        "OMNIBASE_INFRA_DB_URL",
        os.getenv("DATABASE_URL", ""),
    )
    if not db_url:
        return

    conn = psycopg2.connect(db_url)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO skill_usage (skill_name, session_id, invoked_at)
                    VALUES (%(skill_name)s, %(session_id)s, %(invoked_at)s)
                    """,
                    {
                        "skill_name": entry["skill_name"],
                        "session_id": entry["session_id"],
                        "invoked_at": entry["timestamp"],
                    },
                )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI entry-point (called from bash hook via: python skill_usage_logger.py)
# ---------------------------------------------------------------------------


def _main() -> None:
    """Read hook JSON from stdin; append skill usage entry if tool is Skill."""
    import sys

    raw = sys.stdin.read()
    if not raw.strip():
        sys.exit(0)

    try:
        hook_data: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    tool_name: str = hook_data.get("tool_name", "")
    if tool_name != "Skill":
        sys.exit(0)

    tool_input: dict[str, Any] = hook_data.get("tool_input", {})
    skill_name = tool_input.get("skill") or tool_input.get("name") or ""
    session_id = hook_data.get("sessionId") or hook_data.get("session_id") or ""

    append_skill_usage(skill_name=skill_name, session_id=session_id)
    sys.exit(0)


if __name__ == "__main__":
    _main()
