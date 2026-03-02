#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Pre-existing Issue Dedup Lock — prevent concurrent fixes of the same pre-existing issue.

When multiple ticket-pipeline workers are active (e.g. epic-team spawning N workers),
each worker runs pre-commit and mypy independently. Without a distributed lock, two
workers can both discover the same pre-existing violation (e.g. an E501 in a shared
file) and attempt to fix it simultaneously — producing duplicate PRs, merge conflicts,
or divergent fixes.

File-based distributed lock keyed on the issue fingerprint:  # ai-slop-ok: module description

    ``~/.claude/pipeline-locks/preexisting/<fingerprint>.lock``

Lock lifecycle:
    - **Acquire**: before starting a 'chore: fix pre-existing' commit
    - **Release**: after the fix PR is merged, or on timeout (default 30 min)
    - **Skip**: if lock held by another process, caller skips fix and logs a message

The lock file contains JSON metadata (owner run_id, acquired_at, ticket_id) for
debugging and forced expiry.

Usage::

    from preexisting_fix_lock import PreexistingFixLock

    lock = PreexistingFixLock()

    # Compute fingerprint as: sha256(f"{repo}:{rule}:{file}:{error_class}:{line}").hexdigest()[:12]
    fingerprint = "preexisting01"  # example 12-char fingerprint

    if lock.acquire(fingerprint, run_id="epic-OMN-3266-abc", ticket_id="OMN-3260"):
        try:
            # ... apply fix, commit ...
            pass
        finally:
            lock.release(fingerprint)
    else:
        holder = lock.holder(fingerprint)
        print(f"Pre-existing fix in progress by run {holder['run_id']}, skipping.")

Related Tickets:
    - OMN-3260: Pre-existing issue dedup lock (this implementation)

.. versionadded:: 0.3.1
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

__all__ = ["PreexistingFixLock"]

_LOCK_DIR = Path.home() / ".claude" / "pipeline-locks" / "preexisting"
_DEFAULT_TIMEOUT_SECONDS = 30 * 60  # 30 minutes


class PreexistingFixLock:
    """File-based distributed lock for pre-existing issue fixes.

    Thread/process safety: Uses O_CREAT|O_EXCL open semantics for atomic acquisition.
    This is safe across processes on the same filesystem (local or NFS with proper
    lock semantics). It is not safe across machines sharing a network filesystem
    without ``fcntl.flock()`` — but all pipeline workers run on the same host.

    Args:
        lock_dir: Directory for lock files. Defaults to
            ``~/.claude/pipeline-locks/preexisting/``.
        timeout_seconds: Seconds after which a lock is considered stale and may be
            forcibly released. Defaults to 1800 (30 minutes).
    """

    def __init__(
        self,
        lock_dir: Path | None = None,
        timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._lock_dir = lock_dir or _LOCK_DIR
        self._timeout_seconds = timeout_seconds

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def acquire(
        self,
        fingerprint: str,
        run_id: str,
        ticket_id: str,
    ) -> bool:
        """Attempt to acquire the lock for *fingerprint*.

        Returns ``True`` if the lock was successfully acquired (the caller may
        proceed with the fix).  Returns ``False`` if the lock is currently held
        by another run (the caller should skip the fix and log accordingly).

        Stale locks (older than ``timeout_seconds``) are broken automatically
        before the acquisition attempt.

        Args:
            fingerprint: Issue fingerprint (sha256 hex digest, 12 chars).
            run_id: Unique run identifier (e.g. ``epic-OMN-3266-d2ed073f``).
            ticket_id: Ticket being processed (e.g. ``OMN-3260``), for metadata.

        Returns:
            ``True`` if lock acquired; ``False`` if held by another process.
        """
        self._lock_dir.mkdir(parents=True, exist_ok=True)
        lock_path = self._lock_path(fingerprint)

        # Break stale lock before attempting acquisition.
        self._break_if_stale(lock_path)

        payload = json.dumps(
            {
                "run_id": run_id,
                "ticket_id": ticket_id,
                "acquired_at": datetime.now(UTC).isoformat(),
                "fingerprint": fingerprint,
            }
        ).encode()

        try:
            # O_CREAT | O_EXCL is atomic: fails if file already exists.
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            return False

        try:
            os.write(fd, payload)
        finally:
            os.close(fd)

        return True

    def release(self, fingerprint: str) -> None:
        """Release the lock for *fingerprint*.

        Idempotent: silently returns if the lock file does not exist.

        Args:
            fingerprint: Issue fingerprint that was previously locked.
        """
        lock_path = self._lock_path(fingerprint)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass

    def is_locked(self, fingerprint: str) -> bool:
        """Return ``True`` if *fingerprint* is currently locked (and not stale).

        Args:
            fingerprint: Issue fingerprint to check.
        """
        lock_path = self._lock_path(fingerprint)
        self._break_if_stale(lock_path)
        return lock_path.exists()

    def holder(self, fingerprint: str) -> dict[str, str] | None:
        """Return the lock metadata dict for *fingerprint*, or ``None`` if not locked.

        The returned dict has keys: ``run_id``, ``ticket_id``, ``acquired_at``,
        ``fingerprint``.

        Args:
            fingerprint: Issue fingerprint to inspect.
        """
        lock_path = self._lock_path(fingerprint)
        self._break_if_stale(lock_path)
        if not lock_path.exists():
            return None
        try:
            return json.loads(lock_path.read_text())  # type: ignore[no-any-return]
        except (json.JSONDecodeError, OSError):
            return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _lock_path(self, fingerprint: str) -> Path:
        return self._lock_dir / f"{fingerprint}.lock"

    def _break_if_stale(self, lock_path: Path) -> None:
        """Remove *lock_path* if it is older than ``timeout_seconds``."""
        if not lock_path.exists():
            return
        try:
            mtime = lock_path.stat().st_mtime
        except OSError:
            return
        age = time.time() - mtime
        if age > self._timeout_seconds:
            try:
                lock_path.unlink()
            except OSError:
                pass
