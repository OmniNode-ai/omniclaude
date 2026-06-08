# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Pytest wrapper around test_checkout_occ_contracts.sh [OMN-12564].

The shell script holds the actual assertions because the system under test is
``scripts/deploy-gate/checkout-occ-contracts.sh`` — a bash script. This wrapper
exists so the suite is discovered by ``uv run pytest tests/`` and runs in CI
alongside the rest of the suite.

It proves the OCC partial-clone checkout is bounded (an injected slow fetch
terminates at the timeout instead of spinning) and self-diagnosing (the full
diagnostic block, including a process tree, is emitted on failure).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "tests" / "scripts" / "test_checkout_occ_contracts.sh"


@pytest.mark.unit
def test_checkout_occ_contracts_shell_suite() -> None:
    """Run the shell-script test suite for checkout-occ-contracts.sh."""
    assert SCRIPT.is_file(), f"shell test missing: {SCRIPT}"
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": os.environ.get("PATH", "")},
        check=False,
        timeout=300,
    )
    if result.returncode != 0:
        msg = (
            f"checkout-occ-contracts shell tests failed (exit {result.returncode})\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )
        pytest.fail(msg)
    assert "ALL TESTS PASSED" in result.stdout, (
        f"shell tests did not report success:\n{result.stdout}"
    )
