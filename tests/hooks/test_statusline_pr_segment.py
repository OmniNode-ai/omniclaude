# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""CI wiring for the OMN-18841 status-line open-PR segment suite.

The assertions live in ``test_statusline_pr_segment.sh``, because the surface
under test is a bash script and the defect was in its own control flow. This
module exists so the suite runs under the ``uv run pytest tests/hooks/`` job
rather than only when someone remembers to invoke it: a detection tool that is
not a gate is advisory, and advisory checks get ignored (Operating Rule 5).
"""

import subprocess
from pathlib import Path

import pytest

SUITE = Path(__file__).with_suffix(".sh")


@pytest.mark.unit
def test_statusline_pr_segment_never_renders_a_failed_refresh_as_absence() -> None:
    """A failed refresh, a genuine fleet-wide zero and real counts must differ.

    Before OMN-18841 all three rendered as nothing at all, because every ``gh``
    failure was coerced to ``0/0`` and the renderer drops a zero.
    """
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
