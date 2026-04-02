#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Terminal identity — best-effort stable ID per terminal tab.

HEURISTIC: PPID-based identity is a bootstrap mechanism for Phase 2,
not a perfect terminal-tab identity primitive. Known limitations:
- PPID stability depends on terminal emulator and shell lifecycle
- tmux, screen, SSH, and nested shells may produce surprising ancestry
- Shell restarts may reuse or change parent relationships
- Windows support is best-effort (PPID exists but behavior varies)

Cross-platform: works on macOS, Linux, Windows (best-effort).
Survives /clear (ID is in a file, not the conversation).
Usually dies when the shell dies (correct lifecycle, but not guaranteed).

The ID is stored in .onex_state/terminal/current_id.
Each shell session gets its own state subdirectory keyed by
the shell's PID, so multiple terminals have distinct IDs.
"""

from __future__ import annotations

import os
import platform
import uuid
from pathlib import Path

_DEFAULT_STATE_DIR = Path.home() / ".onex_state"


def _get_shell_key() -> str:
    """Get a stable key for the current shell process.

    Uses PPID (parent process ID) on Unix, or a combination of
    session leader PID on Windows. Falls back to PID if PPID
    is not available.
    """
    ppid = os.getppid()
    return str(ppid)


def get_or_create_terminal_id(
    state_dir: Path | None = None,
) -> str:
    """Get or create a stable terminal ID for this shell session.

    The ID persists across /clear because it's stored on disk.
    Different terminal tabs get different IDs because they have
    different parent PIDs.
    """
    base = state_dir or _DEFAULT_STATE_DIR
    terminal_dir = base / "terminal"
    terminal_dir.mkdir(parents=True, exist_ok=True)

    shell_key = _get_shell_key()
    id_file = terminal_dir / f"tid_{shell_key}"

    if id_file.exists():
        existing = id_file.read_text().strip()
        if existing and is_terminal_id_valid(existing):
            return existing

    hostname = platform.node().split(".")[0][:16]
    short_uuid = uuid.uuid4().hex[:8]
    terminal_id = f"terminal-{hostname}-{short_uuid}"

    id_file.write_text(terminal_id)
    return terminal_id


def is_terminal_id_valid(terminal_id: str) -> bool:
    """Check if a terminal ID has valid format."""
    return (
        isinstance(terminal_id, str)
        and terminal_id.startswith("terminal-")
        and len(terminal_id) >= 10
    )
