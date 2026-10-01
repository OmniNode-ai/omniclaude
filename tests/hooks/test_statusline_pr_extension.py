# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""CI wiring for the OMN-20285 status-line PR extension and launcher suite.

The assertions live in ``test_statusline_pr_extension.sh`` because the surface
under test is a bash script. This module runs it under ``pytest tests/hooks/``.
"""

import subprocess
from pathlib import Path

import pytest

SUITE = Path(__file__).with_suffix(".sh")


@pytest.mark.unit
def test_statusline_pr_extension_is_bounded_cached_and_optional() -> None:
    result = subprocess.run(
        ["bash", str(SUITE)],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, (
        f"{SUITE.name} failed (exit {result.returncode})\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
