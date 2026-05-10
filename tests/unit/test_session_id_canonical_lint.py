# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Verify the session-id-canonical lint script rejects legacy reads."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / ".pre-commit-hooks" / "reject-legacy-session-id-reads.sh"


def test_script_exists_and_executable() -> None:
    assert SCRIPT.is_file(), "lint script missing"
    assert os.access(SCRIPT, os.X_OK), "lint script not executable"


def test_rejects_python_legacy_read(tmp_path: Path) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text('import os\nx = os.environ.get("CLAUDE_SESSION_ID", "")\n')
    proc = subprocess.run(
        [str(SCRIPT), str(bad)], capture_output=True, text=True, check=False
    )
    assert proc.returncode != 0
    assert "CLAUDE_SESSION_ID" in proc.stdout + proc.stderr


def test_rejects_shell_legacy_read(tmp_path: Path) -> None:
    bad = tmp_path / "bad.sh"
    bad.write_text('#!/bin/bash\nFOO="${CLAUDE_SESSION_ID:-x}"\n')
    proc = subprocess.run(
        [str(SCRIPT), str(bad)], capture_output=True, text=True, check=False
    )
    assert proc.returncode != 0


def test_accepts_canonical_read(tmp_path: Path) -> None:
    good = tmp_path / "good.py"
    good.write_text('import os\nx = os.environ.get("CLAUDE_CODE_SESSION_ID", "")\n')
    proc = subprocess.run(
        [str(SCRIPT), str(good)], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0


def test_accepts_resolver_module(tmp_path: Path) -> None:
    """The resolver module itself is the only allowed legacy reader."""
    resolver = tmp_path / "session_id.py"
    resolver.write_text('os.environ.get("CLAUDE_SESSION_ID", "")')
    proc = subprocess.run(
        [str(SCRIPT), "--allowlist-name", "session_id.py", str(resolver)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
