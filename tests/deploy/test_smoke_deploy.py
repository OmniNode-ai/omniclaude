# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Pytest wrapper for smoke_deploy.sh — CI integration for deploy integrity.

Runs the post-deploy smoke test runner against the local plugin tree.
This validates pre-ship integrity; the actual post-deploy smoke runs
against the deployed cache path.

[OMN-6370]
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

# Locate the plugin root relative to this test file
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PLUGIN_ROOT = _REPO_ROOT / "plugins" / "onex"
_SMOKE_SCRIPT = _PLUGIN_ROOT / "tests" / "smoke_deploy.sh"


@pytest.mark.integration
def test_smoke_deploy_passes_on_local_plugin_tree() -> None:
    """Run smoke_deploy.sh against the local plugin tree and assert it passes."""
    assert _SMOKE_SCRIPT.exists(), f"Smoke script not found: {_SMOKE_SCRIPT}"
    assert _PLUGIN_ROOT.exists(), f"Plugin root not found: {_PLUGIN_ROOT}"

    result = subprocess.run(
        ["bash", str(_SMOKE_SCRIPT), str(_PLUGIN_ROOT)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(_REPO_ROOT),
        check=False,
    )

    # Print output for CI visibility
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)

    assert result.returncode == 0, (
        f"smoke_deploy.sh failed with exit code {result.returncode}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    assert "SMOKE TEST PASSED" in result.stdout, (
        f"Expected 'SMOKE TEST PASSED' in stdout but got:\n{result.stdout}"
    )
