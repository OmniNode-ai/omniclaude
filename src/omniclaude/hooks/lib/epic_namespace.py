# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Epic execution namespace isolation.

Prevents agent dispatch conflicts when epic-team and autopilot run in the
same session. When epic-team is active, it writes a namespace lock file.
Non-epic dispatches (autopilot sweeps, ad-hoc agents) check the lock and
add an explicit exclusion marker to their dispatch context.

Design:
    - Lock file: $ONEX_STATE_DIR/epics/active_namespace.yaml
    - Written by epic-team at start, removed at end
    - Non-epic dispatches read the file and add 'epic_namespace_exclude: true'
      to their dispatch context, which the agent routing layer uses to
      route them independently of the team mailbox.

Related:
    - OMN-6743: parallel epic execution isolation
    - plugins/onex/skills/epic_team/prompt.md: epic-team orchestration
    - plugins/onex/skills/autopilot/prompt.md: autopilot close-out
"""

from __future__ import annotations

import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


# =============================================================================
# Models
# =============================================================================


class ModelEpicNamespaceLock(BaseModel):
    """Lock file content for active epic namespace."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    epic_id: str = Field(..., description="Active epic ID (e.g., OMN-1234)")
    run_id: str = Field(..., description="Epic run identifier")
    started_at: datetime = Field(..., description="When the epic run started")
    session_id: str = Field(..., description="Claude Code session ID")


# =============================================================================
# Lock file operations
# =============================================================================

_STATE_DIR_ENV = "ONEX_STATE_DIR"
_DEFAULT_STATE_DIR = os.path.expanduser("~/.onex_state")
_LOCK_FILENAME = "active_namespace.yaml"


def _read_lock_data(lock_file: Path) -> dict[str, Any] | None:
    """Read and parse lock file content, trying yaml then json."""
    content = lock_file.read_text()
    try:
        import yaml

        return yaml.safe_load(content)  # type: ignore[no-any-return]
    except ImportError:
        pass
    import json

    return json.loads(content)  # type: ignore[no-any-return]


def _serialize_lock(lock: ModelEpicNamespaceLock) -> str:
    """Serialize lock to yaml (preferred) or json."""
    try:
        import yaml

        return yaml.dump(lock.model_dump(mode="json"), default_flow_style=False)
    except ImportError:
        import json

        return json.dumps(lock.model_dump(mode="json"), indent=2)


def _lock_path() -> Path:
    """Resolve the namespace lock file path."""
    raw = os.environ.get(_STATE_DIR_ENV, _DEFAULT_STATE_DIR).strip()
    state_dir = raw or _DEFAULT_STATE_DIR
    return Path(state_dir).expanduser().resolve() / "epics" / _LOCK_FILENAME


def acquire_namespace(
    epic_id: str,
    run_id: str,
    session_id: str,
    *,
    started_at: datetime | None = None,
) -> bool:
    """Acquire the epic namespace lock.

    Called by epic-team at the start of a run. If another epic is already
    active, returns False (does not overwrite).

    Args:
        epic_id: The epic being executed.
        run_id: Unique run identifier.
        session_id: Claude Code session ID.
        started_at: Lock timestamp. Defaults to now(UTC).

    Returns:
        True if the lock was acquired, False if another epic owns it.
    """
    if started_at is None:
        started_at = datetime.now(UTC)

    lock_file = _lock_path()

    # Check for existing lock
    if lock_file.exists():
        try:
            existing = _read_lock_data(lock_file)
            if existing and existing.get("epic_id") != epic_id:
                logger.warning(
                    "Namespace locked by %s (run %s), cannot acquire for %s",
                    existing.get("epic_id"),
                    existing.get("run_id"),
                    epic_id,
                )
                return False
            # Same epic but different run — don't overwrite
            if (
                existing
                and existing.get("epic_id") == epic_id
                and existing.get("run_id") != run_id
            ):
                logger.warning(
                    "Namespace locked by same epic %s but different run %s, "
                    "cannot acquire for run %s",
                    epic_id,
                    existing.get("run_id"),
                    run_id,
                )
                return False
        except Exception:  # noqa: BLE001 — best-effort lock check
            logger.warning("Failed to read existing namespace lock, overwriting")

    # Write lock atomically via temp file + rename
    lock = ModelEpicNamespaceLock(
        epic_id=epic_id,
        run_id=run_id,
        started_at=started_at,
        session_id=session_id,
    )

    lock_file.parent.mkdir(parents=True, exist_ok=True)

    lock_content = _serialize_lock(lock)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(lock_file.parent), suffix=".tmp", prefix=".lock-"
    )
    try:
        with os.fdopen(fd, "w") as f:
            f.write(lock_content)
        Path(tmp_path).replace(lock_file)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise

    logger.info("Namespace acquired for %s (run %s)", epic_id, run_id)
    return True


def release_namespace(epic_id: str, *, run_id: str | None = None) -> bool:
    """Release the epic namespace lock.

    Called by epic-team at the end of a run. Only releases if the lock
    belongs to the given epic_id (and optionally run_id).

    Args:
        epic_id: The epic that owns the lock.
        run_id: If provided, also validate run ownership.

    Returns:
        True if the lock was released.
    """
    lock_file = _lock_path()

    if not lock_file.exists():
        return True

    try:
        existing = _read_lock_data(lock_file)
    except Exception:  # noqa: BLE001
        logger.warning(
            "Failed to read namespace lock for ownership check, refusing to release"
        )
        return False

    if existing and existing.get("epic_id") != epic_id:
        logger.warning(
            "Cannot release namespace: owned by %s, not %s",
            existing.get("epic_id"),
            epic_id,
        )
        return False

    if run_id and existing and existing.get("run_id") != run_id:
        logger.warning(
            "Cannot release namespace: owned by run %s, not %s",
            existing.get("run_id"),
            run_id,
        )
        return False

    lock_file.unlink(missing_ok=True)
    logger.info("Namespace released for %s", epic_id)
    return True


def get_active_namespace() -> ModelEpicNamespaceLock | None:
    """Check if an epic namespace is currently active.

    Returns:
        The active namespace lock, or None if no epic is active.
    """
    lock_file = _lock_path()

    if not lock_file.exists():
        return None

    try:
        data = _read_lock_data(lock_file)
        if data:
            return ModelEpicNamespaceLock(**data)
    except Exception:  # noqa: BLE001 — best-effort read
        logger.warning("Failed to read namespace lock", exc_info=True)

    return None


def is_epic_active() -> bool:
    """Quick check if any epic is currently running.

    Returns:
        True if an epic namespace lock exists.
    """
    return _lock_path().exists()


def build_isolation_context() -> dict[str, object]:
    """Build dispatch context additions for non-epic agent dispatches.

    When an epic is active, this returns context markers that the agent
    routing layer uses to route the dispatch independently of the team
    mailbox.

    Returns:
        Dict with isolation markers, or empty dict if no epic is active.
    """
    ns = get_active_namespace()
    if ns is None:
        return {}

    return {
        "epic_namespace_exclude": True,
        "active_epic_id": ns.epic_id,
        "active_epic_run_id": ns.run_id,
        "isolation_reason": (
            f"Epic {ns.epic_id} is active in this session. "
            "This dispatch is routed independently to avoid team mailbox conflicts."
        ),
    }
