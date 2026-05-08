# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Pytest wrapper around test_install_delegation.sh [OMN-10626].

The shell script holds the actual assertions because the system under test is
``scripts/install-delegation.sh``. This wrapper exists so the test is
discovered by ``uv run pytest tests/`` and runs in CI alongside the rest of
the suite.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "tests" / "scripts" / "test_install_delegation.sh"


@pytest.mark.unit
def test_install_delegation_shell_suite() -> None:
    """Run the shell-script test suite for install-delegation.sh."""
    assert SCRIPT.is_file(), f"shell test missing: {SCRIPT}"
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": os.environ.get("PATH", "")},
        check=False,
    )
    if result.returncode != 0:
        msg = (
            f"install-delegation shell tests failed (exit {result.returncode})\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )
        pytest.fail(msg)
    assert "ALL TESTS PASSED" in result.stdout, (
        f"shell tests did not report success:\n{result.stdout}"
    )
