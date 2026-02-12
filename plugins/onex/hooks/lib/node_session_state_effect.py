#!/usr/bin/env python3
"""Session State Effect Node - Declarative filesystem I/O for session state.

G1 node: All filesystem operations on ~/.claude/state/.

Provides:
    - Atomic writes (tmp + fsync + rename)
    - flock-based concurrency control with configurable timeout
    - Time-gated garbage collection of stale run documents
    - Typed Pydantic contracts for session index and run context

Related Tickets:
    - OMN-2119: Session State Orchestrator Shim + Adapter

.. versionadded:: 0.2.1
"""

from __future__ import annotations

import enum
import fcntl
import json
import os
import re
import threading
import time
from collections.abc import Callable
from datetime import UTC
from pathlib import Path

from pydantic import BaseModel, ConfigDict

# =============================================================================
# Contract-style Configuration (via env vars)
# =============================================================================

CLAUDE_STATE_DIR = os.environ.get(
    "CLAUDE_STATE_DIR", str(Path.home() / ".claude" / "state")
)
CLAUDE_STATE_LOCK_TIMEOUT_MS = int(
    os.environ.get("CLAUDE_STATE_LOCK_TIMEOUT_MS", "100")
)
CLAUDE_STATE_GC_TTL_SECONDS = int(
    os.environ.get("CLAUDE_STATE_GC_TTL_SECONDS", "14400")
)

# GC runs at most once per this interval
_GC_INTERVAL_SECONDS = 600  # 10 minutes


# =============================================================================
# Pydantic Contracts
# =============================================================================


class ContractSessionIndex(BaseModel):
    """Session index tracking active and recent runs."""

    model_config = ConfigDict(extra="ignore")

    active_run_id: str | None = None
    recent_run_ids: list[str] = []
    updated_at: str = ""


class ContractRunContext(BaseModel):
    """Individual run context document."""

    model_config = ConfigDict(extra="ignore")

    run_id: str
    session_id: str
    state: str = "idle"
    created_at: str = ""
    updated_at: str = ""


# =============================================================================
# Lock Result
# =============================================================================


class LockResult(enum.Enum):
    """Result of a flock acquisition attempt."""

    ACQUIRED = "acquired"
    TIMEOUT = "timeout"
    ERROR = "error"


# =============================================================================
# Internal Helpers
# =============================================================================


def _state_dir() -> Path:
    """Return the configured state directory."""
    return Path(CLAUDE_STATE_DIR)


def _runs_dir() -> Path:
    """Return the runs subdirectory."""
    return _state_dir() / "runs"


def _session_index_path() -> Path:
    """Return the path to session.json."""
    return _state_dir() / "session.json"


_SAFE_RUN_ID_RE = re.compile(r"^[a-zA-Z0-9\-]+$")


def _validate_run_id(run_id: str) -> None:
    """Validate run_id to prevent path traversal.

    Accepts only alphanumeric characters and hyphens (covers uuid4 format).
    Raises ValueError for any run_id containing path separators, parent
    directory references, or other unsafe characters.
    """
    if not run_id:
        raise ValueError("run_id must not be empty")
    if not _SAFE_RUN_ID_RE.match(run_id):
        raise ValueError(
            f"Invalid run_id: {run_id!r}. "
            "Only alphanumeric characters and hyphens are allowed."
        )


def _run_context_path(run_id: str) -> Path:
    """Return the path to a run context file.

    Validates run_id to prevent path traversal attacks.

    Raises:
        ValueError: If run_id contains unsafe characters.
    """
    _validate_run_id(run_id)
    return _runs_dir() / f"{run_id}.json"


def _gc_stamp_path() -> Path:
    """Return the path to the GC stamp file."""
    return _state_dir() / ".gc_last_run"


def _acquire_lock(lock_path: Path, timeout_ms: int) -> tuple[LockResult, int]:
    """Non-blocking flock with timeout.

    Args:
        lock_path: Path to the lock file.
        timeout_ms: Maximum time to wait for the lock in milliseconds.

    Returns:
        Tuple of (LockResult, file_descriptor). On ACQUIRED, caller must
        os.close(fd) when done. On TIMEOUT or ERROR, fd is -1.
    """
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    fd = -1
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return LockResult.ACQUIRED, fd
            except OSError:
                if time.monotonic() >= deadline:
                    os.close(fd)
                    return LockResult.TIMEOUT, -1
                time.sleep(0.005)  # 5ms retry
    except Exception:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        return LockResult.ERROR, -1


def _release_lock(fd: int) -> None:
    """Release a lock acquired by _acquire_lock."""
    if fd >= 0:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass


def _atomic_write(target: Path, data: str) -> None:
    """Atomic write: write to tmp, fsync, rename.

    Args:
        target: Final file path.
        data: String content to write.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.parent / f".tmp.{os.getpid()}.{threading.get_ident()}"
    fd = os.open(str(tmp_path), os.O_CREAT | os.O_WRONLY | os.O_TRUNC)
    try:
        os.write(fd, data.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    tmp_path.rename(target)


# =============================================================================
# Handler Functions
# =============================================================================


def read_session_index() -> ContractSessionIndex:
    """Read and parse the session index file.

    Returns:
        ContractSessionIndex parsed from disk, or a default empty index
        if the file does not exist or is invalid.
    """
    path = _session_index_path()
    try:
        if not path.exists():
            return ContractSessionIndex()
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        return ContractSessionIndex(**data)
    except Exception:
        return ContractSessionIndex()


def write_session_index(index: ContractSessionIndex) -> LockResult:
    """Write the session index atomically with flock.

    Args:
        index: The session index to persist.

    Returns:
        LockResult indicating whether the write succeeded.
    """
    path = _session_index_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    # Lock on a dedicated lock file, NOT session.json itself.
    # _atomic_write replaces session.json via rename (new inode), so locking
    # on session.json would let concurrent processes each lock different inodes.
    # A stable lock file that is never renamed provides true mutual exclusion.
    lock_path = path.parent / "session.json.lock"
    result, fd = _acquire_lock(lock_path, CLAUDE_STATE_LOCK_TIMEOUT_MS)
    if result != LockResult.ACQUIRED:
        return result

    try:
        _atomic_write(path, index.model_dump_json(indent=2))
        return LockResult.ACQUIRED
    finally:
        _release_lock(fd)


def read_run_context(run_id: str) -> ContractRunContext | None:
    """Read a run context document.

    Args:
        run_id: The run identifier.

    Returns:
        ContractRunContext if found and valid, None otherwise.
    """
    path = _run_context_path(run_id)
    try:
        if not path.exists():
            return None
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        return ContractRunContext(**data)
    except Exception:
        return None


def write_run_context(ctx: ContractRunContext) -> None:
    """Write a run context document atomically.

    Args:
        ctx: The run context to persist.
    """
    path = _run_context_path(ctx.run_id)
    _atomic_write(path, ctx.model_dump_json(indent=2))


def gc_stale_runs() -> int:
    """Garbage-collect stale run documents.

    Removes run docs where state == "run_ended" AND older than GC TTL.
    Time-gated via stamp file to run at most once per 10 minutes.

    Returns:
        Number of run documents removed.
    """
    stamp = _gc_stamp_path()

    # O(1) time-gate check
    try:
        if stamp.exists():
            age = time.time() - stamp.stat().st_mtime
            if age < _GC_INTERVAL_SECONDS:
                return 0
    except OSError:
        pass

    # Update stamp file (even if GC finds nothing)
    try:
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(str(time.time()))
    except OSError:
        pass

    runs_dir = _runs_dir()
    if not runs_dir.exists():
        return 0

    removed = 0
    now = time.time()
    cutoff = now - CLAUDE_STATE_GC_TTL_SECONDS

    # Import here (not at module level) since datetime is only needed for GC
    from datetime import datetime

    try:
        for path in runs_dir.iterdir():
            if not path.name.endswith(".json"):
                continue
            try:
                raw = path.read_text(encoding="utf-8")
                data = json.loads(raw)
                ctx = ContractRunContext(**data)
                if ctx.state == "run_ended" and ctx.updated_at:
                    # Parse ISO timestamp to epoch for comparison
                    updated = datetime.fromisoformat(ctx.updated_at)
                    if updated.tzinfo is None:
                        updated = updated.replace(tzinfo=UTC)
                    if updated.timestamp() < cutoff:
                        path.unlink()
                        removed += 1
            except Exception:
                continue
    except OSError:
        pass

    return removed


# =============================================================================
# Handler Registry
# =============================================================================

HANDLERS: dict[str, Callable] = {
    "read_session_index": read_session_index,
    "write_session_index": write_session_index,
    "read_run_context": read_run_context,
    "write_run_context": write_run_context,
    "gc_stale_runs": gc_stale_runs,
}
