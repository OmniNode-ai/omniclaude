# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""CI gate for OMN-18841: the statusline open-PR segment is never a silent zero.

The behaviour lives in a shell script, so the assertions live in a shell suite
(`test_statusline_pr_segment.sh`). This wrapper is what puts that suite inside
the required `tests/hooks/` pytest job, which discovers `test_*.py` only — a
detection surface nothing runs is advisory, and this one has to block.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

SUITE = Path(__file__).with_suffix(".sh")


@pytest.mark.unit
def test_statusline_pr_segment_shell_suite_passes() -> None:
    """Every state of the open-PR segment renders distinguishably."""
    assert SUITE.exists(), f"shell suite missing at {SUITE}"

    if shutil.which("jq") is None:
        pytest.skip("jq not installed; the suite renders JSON fixtures")

    result = subprocess.run(
        ["bash", str(SUITE), "--verbose"],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, (
        f"statusline open-PR segment suite failed (exit {result.returncode}):\n"
        f"{result.stdout}\n{result.stderr}"
    )
