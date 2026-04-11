# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""pytest DoD gate for OMN-8438: stable statusline shim.

The single required test name is mandated by the ticket contract:
  test_statusline_shim_resolves_to_stable_path
"""

import os
import subprocess
from pathlib import Path


def test_statusline_shim_resolves_to_stable_path() -> None:
    """Shim at $HOME/.onex_state/bin/statusline.sh must exist, be executable,
    contain no hardcoded version string, and produce output when invoked."""
    home = Path.home()
    shim = home / ".onex_state" / "bin" / "statusline.sh"

    assert shim.exists(), f"Stable shim not found at {shim} — run deploy.sh first"
    assert os.access(shim, os.X_OK), f"Shim at {shim} is not executable"

    content = shim.read_text()
    # Must not contain a hardcoded semver cache path like .../onex/2.2.5/...
    import re

    assert not re.search(r"/cache/omninode-tools/onex/\d+\.\d+\.\d+/", content), (
        "Shim contains a hardcoded version path — must use dynamic discovery"
    )

    # Must reference dynamic cache discovery
    assert "omninode-tools/onex" in content, (
        "Shim does not reference the plugin cache root"
    )

    # Shim must produce non-empty output when fed mock usage JSON
    mock_usage = (
        '{"model":{"display_name":"Claude Opus 4.6","id":"claude-opus-4-6"},'
        '"tokens":{"used":50000,"total":100000},'
        '"plan_usage":{"current_period":{"utilization":45.0,"reset_at":"2026-03-06T00:00:00Z"},'
        '"weekly":{"utilization":30.0,"reset_at":"2026-03-10T00:00:00Z"}},'
        '"thinking":{"enabled":true,"budget_tokens":16000}}'
    )
    result = subprocess.run(
        ["bash", str(shim)],
        input=mock_usage,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.stdout.strip(), (
        "Shim produced no output when invoked with mock usage JSON"
    )
