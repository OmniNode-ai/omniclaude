# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Background watcher for STANDALONE mode.

Spawns ``gh run watch`` as background processes to monitor CI runs.
Max 5 concurrent watchers. Per-PR lock files prevent duplicate watchers.
Inbox filenames include run_id for idempotency.

See OMN-2826 Phase 2d for specification.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = [
    "BackgroundWatcher",
    "INBOX_TTL_SECONDS",
    "MAX_WATCHERS",
]

# Max concurrent background watchers
MAX_WATCHERS = int(os.environ.get("OMNICLAUDE_MAX_WATCHERS", "5"))

# TTL for inbox files and lock files (2 hours)
INBOX_TTL_SECONDS = 7200


def _inbox_dir() -> Path:
    """Get the inbox directory, creating it if needed."""
    from omniclaude.services.standalone_inbox.inbox import _inbox_dir as _base_inbox_dir

    d = _base_inbox_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _lock_dir() -> Path:
    """Get the lock directory, creating it if needed."""
    d = _inbox_dir() / ".locks"
    d.mkdir(parents=True, exist_ok=True)
    return d


class BackgroundWatcher:
    """Manages background ``gh run watch`` processes.

    Each watcher monitors a single CI run and writes the result to a
    file-based inbox when the run completes.

    Attributes:
        inbox_dir: Directory for inbox files.
        lock_dir: Directory for lock files.
    """

    def __init__(self) -> None:
        self.inbox_dir = _inbox_dir()
        self.lock_dir = _lock_dir()

    def _lock_path(self, repo: str, pr_number: int, run_id: int) -> Path:
        """Build lock file path for a watcher."""
        safe_repo = repo.replace("/", "_")
        return self.lock_dir / f"{safe_repo}_pr{pr_number}_run{run_id}.lock"

    def _inbox_path(self, repo: str, pr_number: int, run_id: int) -> Path:
        """Build inbox file path for a watcher result."""
        safe_repo = repo.replace("/", "_")
        return self.inbox_dir / f"{safe_repo}_pr{pr_number}_run{run_id}.json"

    def _count_active_watchers(self) -> int:
        """Count currently active watcher processes by checking lock files."""
        count = 0
        now = time.time()
        for lock_file in self.lock_dir.glob("*.lock"):
            try:
                data = json.loads(lock_file.read_text())
                pid = data.get("pid", 0)
                started = data.get("started_at_epoch", 0)

                # Check if process is still alive
                if pid and self._is_pid_alive(pid):
                    # Also check TTL to avoid counting zombie locks
                    if now - started < INBOX_TTL_SECONDS:
                        count += 1
                    else:
                        # Stale lock -- clean up
                        lock_file.unlink(missing_ok=True)
                else:
                    # Process dead -- clean up lock
                    lock_file.unlink(missing_ok=True)
            except (json.JSONDecodeError, OSError):
                lock_file.unlink(missing_ok=True)
        return count

    @staticmethod
    def _is_pid_alive(pid: int) -> bool:
        """Check if a process is still running."""
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

    def start_watcher(
        self,
        repo: str,
        pr_number: int,
        run_id: int,
    ) -> bool:
        """Start a background watcher for a CI run.

        Spawns ``gh run watch {run_id} --exit-status`` as a background
        process. On completion, writes the result to the file-based inbox.

        Args:
            repo: Full repo slug (e.g. ``OmniNode-ai/omniclaude``).
            pr_number: PR number being watched.
            run_id: GH Actions run ID.

        Returns:
            True if watcher was started, False if at capacity or duplicate.
        """
        lock_path = self._lock_path(repo, pr_number, run_id)
        inbox_path = self._inbox_path(repo, pr_number, run_id)

        # Check for existing lock (duplicate prevention)
        if lock_path.exists():
            try:
                data = json.loads(lock_path.read_text())
                pid = data.get("pid", 0)
                if pid and self._is_pid_alive(pid):
                    logger.info(
                        "Watcher already running: repo=%s pr=%d run=%d pid=%d",
                        repo,
                        pr_number,
                        run_id,
                        pid,
                    )
                    return False
            except (json.JSONDecodeError, OSError):
                pass
            lock_path.unlink(missing_ok=True)

        # Check capacity
        active = self._count_active_watchers()
        if active >= MAX_WATCHERS:
            logger.warning(
                "Watcher capacity reached: %d/%d. Cannot start watcher for "
                "repo=%s pr=%d run=%d",
                active,
                MAX_WATCHERS,
                repo,
                pr_number,
                run_id,
            )
            return False

        # Build the watcher script that runs gh run watch and writes result
        script = f"""
import json, subprocess, sys, tempfile, time
from pathlib import Path

repo = {repo!r}
pr_number = {pr_number!r}
run_id = {run_id!r}
inbox_path = Path({str(inbox_path)!r})

try:
    result = subprocess.run(
        ["gh", "run", "watch", str(run_id), "--repo", repo, "--exit-status"],
        capture_output=True,
        text=True,
        timeout=3600,
    )
    conclusion = "success" if result.returncode == 0 else "failure"
except subprocess.TimeoutExpired:
    conclusion = "timeout"
except Exception as e:
    conclusion = "error"

payload = {{
    "repo": repo,
    "pr": pr_number,
    "run_id": run_id,
    "conclusion": conclusion,
    "timestamp": time.time(),
}}

# Atomic write: temp file + rename
tmp = inbox_path.with_suffix(".tmp")
tmp.write_text(json.dumps(payload, indent=2))
tmp.rename(inbox_path)

# Clean up lock file
lock = Path({str(lock_path)!r})
lock.unlink(missing_ok=True)
"""
        # Write script to temp file and spawn
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(script)
            script_path = f.name

        try:
            proc = subprocess.Popen(
                ["python3", script_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            logger.error("Failed to start watcher process: %s", exc)
            Path(script_path).unlink(missing_ok=True)
            return False

        # Write lock file
        lock_data = {
            "pid": proc.pid,
            "repo": repo,
            "pr_number": pr_number,
            "run_id": run_id,
            "started_at_epoch": time.time(),
            "script_path": script_path,
        }
        lock_path.write_text(json.dumps(lock_data, indent=2))

        logger.info(
            "Watcher started: repo=%s pr=%d run=%d pid=%d",
            repo,
            pr_number,
            run_id,
            proc.pid,
        )
        return True

    def gc_stale_files(self) -> int:
        """Remove inbox and lock files older than TTL.

        Returns:
            Number of files removed.
        """
        now = time.time()
        removed = 0

        # Clean inbox files
        for inbox_file in self.inbox_dir.glob("*.json"):
            try:
                stat = inbox_file.stat()
                if now - stat.st_mtime > INBOX_TTL_SECONDS:
                    inbox_file.unlink(missing_ok=True)
                    removed += 1
            except OSError:
                pass

        # Clean stale locks
        for lock_file in self.lock_dir.glob("*.lock"):
            try:
                data = json.loads(lock_file.read_text())
                started = data.get("started_at_epoch", 0)
                if now - started > INBOX_TTL_SECONDS:
                    lock_file.unlink(missing_ok=True)
                    # Also clean up the script file if it exists
                    script_path = data.get("script_path")
                    if script_path:
                        Path(script_path).unlink(missing_ok=True)
                    removed += 1
            except (json.JSONDecodeError, OSError):
                lock_file.unlink(missing_ok=True)
                removed += 1

        if removed:
            logger.info("GC removed %d stale inbox/lock files", removed)
        return removed
