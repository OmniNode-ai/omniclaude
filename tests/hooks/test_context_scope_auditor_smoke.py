# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Smoke test for pre_tool_use_context_scope_auditor.sh deploy-path bug class.

Regression guard: the script must use the bundled venv Python (via common.sh /
find_python()), not a bare system interpreter with a broken PYTHONPATH.  If the
script regresses to bypassing common.sh it will use bare python3 (no omniclaude
on path) and emit ModuleNotFoundError on every PreToolUse call.

Test strategy
-------------
We point PLUGIN_PYTHON_BIN at a tiny shim script that prints the JSON payload
back to stdout and exits 0 — this verifies the script's Python resolution path
without requiring a working Kafka/DB environment.  The ModuleNotFoundError
assertion is the primary regression signal: before the fix, bare python3 would
fail to import omniclaude.hooks before the shim is even consulted.

The shim is a real executable Python script placed in tmp_path, so common.sh
priority-1 (PLUGIN_PYTHON_BIN) picks it up.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

# Path relative to repo root — skip gracefully when plugin tree is absent
_REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = (
    _REPO_ROOT / "plugins/onex/hooks/scripts/pre_tool_use_context_scope_auditor.sh"
)
VENV_PYTHON = _REPO_ROOT / "plugins/onex/hooks/lib/.venv/bin/python3"

# Minimal Python shim: reads stdin, writes it back to stdout, exits 0.
# Simulates a correct omniclaude handler response without any network deps.
_SHIM_SOURCE = """\
#!/usr/bin/env python3
import sys
data = sys.stdin.read()
sys.stdout.write(data)
sys.exit(0)
"""


def _make_python_shim(tmp_path: Path) -> Path:
    """Write a minimal Python shim that passes through stdin and exits 0."""
    shim = tmp_path / "python3"
    shim.write_text(_SHIM_SOURCE)
    shim.chmod(0o755)
    return shim


@pytest.mark.unit
def test_context_scope_auditor_no_module_error_on_bare_python(tmp_path: Path) -> None:
    """Script must not emit ModuleNotFoundError when common.sh is sourced.

    The fix sources common.sh so find_python() resolves PYTHON_CMD to the
    bundled venv (or PLUGIN_PYTHON_BIN override).  Before the fix, the script
    used bare python3 (system interpreter) with a broken PYTHONPATH, producing:

        ModuleNotFoundError: No module named 'omniclaude.hooks'

    This test uses a Python shim as PLUGIN_PYTHON_BIN so the test does not
    require Kafka, Postgres, or any live infrastructure.  The shim is the
    common.sh priority-1 escape hatch — exactly the mechanism PLUGIN_PYTHON_BIN
    is designed for.

    The signal "no ModuleNotFoundError in stderr" catches the regression: if
    the script reverts to using bare python3 (without common.sh), the error
    fires before the shim receives any input.

    ONEX_STATE_DIR is required by onex-paths.sh (ONEX_HOOK_LOG resolution).
    """
    if not SCRIPT_PATH.exists():
        pytest.skip(f"Script not found: {SCRIPT_PATH}")

    payload = json.dumps(
        {
            "tool_name": "Bash",
            "tool_input": {"command": "echo hello"},
            "session_id": "test-session-001",
        }
    )

    # Write a shim that common.sh will use as PYTHON_CMD (priority 1 override).
    shim = _make_python_shim(tmp_path)

    env = os.environ.copy()
    env["PLUGIN_PYTHON_BIN"] = str(shim)
    env["LOG_FILE"] = str(tmp_path / "hooks.log")
    env["ONEX_STATE_DIR"] = str(tmp_path / "onex_state")
    # Strip omniclaude from the system path so the test exercises the hook's actual
    # venv resolution rather than falling back to a CI interpreter that already has
    # omniclaude installed.  The hook must succeed purely via PLUGIN_PYTHON_BIN or
    # the bundled venv — not via the ambient Python environment.
    env["PYTHONPATH"] = ""
    env["VIRTUAL_ENV"] = ""

    result = subprocess.run(
        ["bash", str(SCRIPT_PATH)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
        check=False,
    )

    # Exit 0 = allow.  The shim echoes the payload, so stdout should be non-empty.
    assert result.returncode == 0, (
        f"Script exited {result.returncode};\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "ModuleNotFoundError" not in result.stderr, (
        f"ModuleNotFoundError in stderr — script is using wrong Python interpreter:\n{result.stderr}"
    )
    assert "No module named" not in result.stderr, (
        f"Import error in stderr — script is using wrong Python interpreter:\n{result.stderr}"
    )
    # The shim echoes stdin back — stdout must contain the original payload.
    assert result.stdout.strip(), (
        "Script produced no stdout — expected JSON pass-through"
    )
