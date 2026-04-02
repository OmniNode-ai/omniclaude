# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for terminal identity generation and persistence."""

import sys
from pathlib import Path

import pytest

# Add hooks/lib to path so we can import the module directly
sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[4] / "plugins" / "onex" / "hooks" / "lib"),
)

from terminal_identity import (  # noqa: E402
    get_or_create_terminal_id,
    is_terminal_id_valid,
)


@pytest.mark.unit
class TestTerminalIdentity:
    def test_creates_new_id(self, tmp_path: Path) -> None:
        tid = get_or_create_terminal_id(state_dir=tmp_path)
        assert tid is not None
        assert len(tid) > 0
        assert is_terminal_id_valid(tid)

    def test_returns_same_id_on_second_call(self, tmp_path: Path) -> None:
        tid1 = get_or_create_terminal_id(state_dir=tmp_path)
        tid2 = get_or_create_terminal_id(state_dir=tmp_path)
        assert tid1 == tid2

    def test_different_dirs_different_ids(self, tmp_path: Path) -> None:
        dir1 = tmp_path / "t1"
        dir2 = tmp_path / "t2"
        dir1.mkdir()
        dir2.mkdir()
        tid1 = get_or_create_terminal_id(state_dir=dir1)
        tid2 = get_or_create_terminal_id(state_dir=dir2)
        assert tid1 != tid2

    def test_id_format(self, tmp_path: Path) -> None:
        tid = get_or_create_terminal_id(state_dir=tmp_path)
        assert tid.startswith("terminal-")
