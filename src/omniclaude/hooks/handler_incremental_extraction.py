# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Incremental extraction hook for Claude Code PostToolUse events.

When Claude Code edits a .py/.ts/.js file (via Edit/Write tools), this hook
emits a code-crawl-requested.v1 command scoped to the changed file. The
existing pipeline (Part 1 handlers) handles the rest.

Debounce: tracks {file_path: last_trigger_time} in memory, skips within
configured debounce_seconds window.

V1 limitations (explicit):
- In-memory debounce state disappears on process restart
- Renames/moves appear as different paths (may create orphans)
- Only batch recrawls guarantee latest-state reconciliation

Reference: OMN-5684
"""

from __future__ import annotations

import logging
import time
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class IncrementalExtractionHandler:
    """PostToolUse hook handler for incremental code extraction.

    All config is read from contract YAML's incremental_extraction section.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        """Initialize from contract config.

        Args:
            config: The ``config.incremental_extraction`` dict.
        """
        self._enabled: bool = config.get("enabled", True)
        self._trigger_tools: set[str] = set(
            config.get("trigger_tools", ["Edit", "Write"])
        )
        self._debounce_seconds: float = config.get("debounce_seconds", 30)
        self._watched_extensions: set[str] = set(
            config.get("watched_extensions", [".py", ".ts", ".js"])
        )
        self._watched_repos: list[dict[str, str]] = config.get("watched_repos", [])
        self._excluded_paths: list[str] = config.get(
            "excluded_paths",
            [
                "tests/**",
                "__pycache__/**",
                "node_modules/**",
            ],
        )

        # In-memory debounce state
        self._last_trigger: dict[str, float] = {}

    @property
    def enabled(self) -> bool:
        return self._enabled

    def should_trigger(self, tool_name: str, file_path: str) -> bool:
        """Check if a PostToolUse event should trigger extraction.

        Args:
            tool_name: Name of the tool that was used (Edit, Write, etc.)
            file_path: Absolute path of the file that was modified.

        Returns:
            True if extraction should be triggered.
        """
        if not self._enabled:
            return False

        # Check tool name
        if tool_name not in self._trigger_tools:
            return False

        # Check file extension
        ext = Path(file_path).suffix
        if ext not in self._watched_extensions:
            return False

        # Check if file is in a watched repo
        if not self._is_in_watched_repo(file_path):
            return False

        # Check excluded paths
        if self._is_excluded(file_path):
            return False

        # Check debounce
        now = time.monotonic()
        last = self._last_trigger.get(file_path, 0.0)
        if now - last < self._debounce_seconds:
            logger.debug(
                "Debounce: skipping %s (%.1fs since last trigger)",
                file_path,
                now - last,
            )
            return False

        # Update debounce state
        self._last_trigger[file_path] = now
        return True

    def build_crawl_command(self, file_path: str) -> dict[str, Any] | None:
        """Build a code-crawl-requested.v1 command payload for a changed file.

        Args:
            file_path: Absolute path of the modified file.

        Returns:
            Command payload dict, or None if file should not trigger.
        """
        repo_info = self._resolve_repo(file_path)
        if repo_info is None:
            return None

        repo_name, relative_path = repo_info

        return {
            "repo_name": repo_name,
            "file_path": relative_path,
            "trigger": "incremental",
            "source": "claude_code_hook",
        }

    def _is_in_watched_repo(self, file_path: str) -> bool:
        """Check if file is under any watched repo path."""
        for repo in self._watched_repos:
            prefix = repo.get("path_prefix", "")
            if prefix and file_path.startswith(prefix):
                return True
        # If no watched_repos configured, allow all
        return len(self._watched_repos) == 0

    def _is_excluded(self, file_path: str) -> bool:
        """Check if file matches any excluded path pattern."""
        for pattern in self._excluded_paths:
            if fnmatch(file_path, f"*/{pattern}") or fnmatch(file_path, pattern):
                return True
        return False

    def _resolve_repo(self, file_path: str) -> tuple[str, str] | None:
        """Resolve file path to (repo_name, relative_path)."""
        for repo in self._watched_repos:
            name = repo.get("name", "")
            prefix = repo.get("path_prefix", "")
            if prefix and file_path.startswith(prefix):
                # Extract relative path after repo name
                after_prefix = file_path[len(prefix) :]
                # Pattern: /TICKET/REPO/rest or just REPO/rest
                parts = Path(after_prefix).parts
                for i, part in enumerate(parts):
                    if part == name:
                        relative = (
                            str(Path(*parts[i + 1 :])) if i + 1 < len(parts) else ""
                        )
                        return name, relative
                # Fallback: use entire path after prefix
                return name, after_prefix

        return None


__all__ = ["IncrementalExtractionHandler"]
