# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""File-based inbox for STANDALONE mode.

Reads notification files written by background watchers. Uses a cursor
file for efficient reads (avoids full directory scan on each check).

See OMN-2826 Phase 2d for specification.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _inbox_dir() -> Path:
    """Get the inbox directory."""
    return Path.home() / ".claude" / "pr-inbox"


class StandaloneInbox:
    """File-based inbox for STANDALONE mode PR notifications.

    Inbox files are written by BackgroundWatcher processes when CI runs
    complete. This class reads those files and provides an interface
    for skills to wait for notifications.

    Uses a cursor file (``.cursor``) with ``last_seen_ts`` to avoid
    full directory scans on repeated checks.
    """

    def __init__(self, inbox_dir: Path | None = None) -> None:
        self._inbox_dir = inbox_dir or _inbox_dir()
        self._cursor_path = self._inbox_dir / ".cursor"

    def _read_cursor(self) -> float:
        """Read the cursor timestamp. Returns 0.0 if no cursor exists."""
        try:
            data = json.loads(self._cursor_path.read_text())
            return float(data.get("last_seen_ts", 0.0))
        except (json.JSONDecodeError, OSError, ValueError):
            return 0.0

    def _write_cursor(self, ts: float) -> None:
        """Write the cursor timestamp."""
        self._cursor_path.write_text(json.dumps({"last_seen_ts": ts}))

    def check_inbox(
        self,
        *,
        repo: str | None = None,
        pr_number: int | None = None,
    ) -> list[dict[str, Any]]:
        """Check for new inbox notifications since last cursor.

        Optionally filters by repo and/or pr_number.

        Args:
            repo: Filter by repo slug (optional).
            pr_number: Filter by PR number (optional).

        Returns:
            List of notification payloads, newest first.
        """
        if not self._inbox_dir.exists():
            return []

        cursor_ts = self._read_cursor()
        results: list[dict[str, Any]] = []
        max_ts = cursor_ts

        for inbox_file in self._inbox_dir.glob("*.json"):
            if inbox_file.name.startswith("."):
                continue
            try:
                stat = inbox_file.stat()
                if stat.st_mtime <= cursor_ts:
                    continue

                data = json.loads(inbox_file.read_text())

                # Apply filters
                if repo and data.get("repo") != repo:
                    continue
                if pr_number is not None and data.get("pr") != pr_number:
                    continue

                results.append(data)
                max_ts = max(max_ts, stat.st_mtime)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to read inbox file %s: %s", inbox_file, exc)

        # Update cursor
        if max_ts > cursor_ts:
            self._write_cursor(max_ts)

        # Sort newest first
        results.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return results

    def wait_for_notification(
        self,
        *,
        repo: str,
        pr_number: int,
        timeout_seconds: int = 3600,
        poll_interval_seconds: int = 10,
    ) -> dict[str, Any] | None:
        """Wait for a notification matching (repo, pr_number).

        Polls the inbox directory at the given interval. Returns None
        on timeout.

        Args:
            repo: Full repo slug.
            pr_number: PR number to wait for.
            timeout_seconds: Max seconds to wait. Default 1 hour.
            poll_interval_seconds: Seconds between polls. Default 10.

        Returns:
            Notification payload dict, or None on timeout.
        """
        start = time.monotonic()

        while time.monotonic() - start < timeout_seconds:
            results = self.check_inbox(repo=repo, pr_number=pr_number)
            if results:
                return results[0]
            time.sleep(poll_interval_seconds)

        logger.warning(
            "Inbox wait timed out: repo=%s pr=%d timeout=%ds",
            repo,
            pr_number,
            timeout_seconds,
        )
        return None

    def get_notification_for_run(
        self, repo: str, pr_number: int, run_id: int
    ) -> dict[str, Any] | None:
        """Get a specific notification by run_id.

        Does not use or update the cursor -- reads the specific file directly.

        Args:
            repo: Full repo slug.
            pr_number: PR number.
            run_id: GH Actions run ID.

        Returns:
            Notification payload dict, or None if not found.
        """
        safe_repo = repo.replace("/", "_")
        inbox_path = self._inbox_dir / f"{safe_repo}_pr{pr_number}_run{run_id}.json"
        if inbox_path.exists():
            try:
                return json.loads(inbox_path.read_text())
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to read inbox file %s: %s", inbox_path, exc)
        return None
