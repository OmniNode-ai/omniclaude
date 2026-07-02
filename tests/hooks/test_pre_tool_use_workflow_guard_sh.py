# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Shell-wrapper regression tests for pre_tool_use_workflow_guard.sh (OMN-13848).

The Python guard (``omniclaude.hooks.pre_tool_use_workflow_guard``) already
blocks Edit/Write to canonical clones. But the shell wrapper sourced
``common.sh`` WITHOUT binding ``PROJECT_ROOT``; under ``set -u`` common.sh's
``${PROJECT_ROOT}/.env`` dereference raised "unbound variable", the wrapper
exited non-zero, and the error-guard EXIT trap swallowed it to exit 0 -- so the
canonical-clone write guard failed OPEN and never reached the Python block.

These tests drive the real shell wrapper end-to-end and assert it now fails
CLOSED (exit 2) on a canonical-clone Edit while still allowing worktree writes.
They deliberately do NOT set PROJECT_ROOT in the environment: the wrapper must
bind it itself. Before the fix these assertions fail (the block returns 0).

Performance note: the wrapper invokes the guard via
``$PYTHON_CMD -m omniclaude.hooks.pre_tool_use_workflow_guard``. Importing that
module through the package ``__init__`` eagerly pulls in the full omnibase_infra
runtime (~tens of seconds cold), which would make this a slow, flaky test. The
guard module itself is stdlib-only, so we point ``PLUGIN_PYTHON_BIN`` at a thin
shim that runs the module *file* directly -- behaviourally identical guard logic
for this self-contained module, minus the heavy package import. The shell
wrapper under test (PROJECT_ROOT binding, exit-code propagation) is exercised in
full.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = (
    _REPO_ROOT
    / "plugins"
    / "onex"
    / "hooks"
    / "scripts"
    / "pre_tool_use_workflow_guard.sh"
)
_PLUGIN_ROOT = _REPO_ROOT / "plugins" / "onex"
_GUARD_MODULE_FILE = (
    _REPO_ROOT / "src" / "omniclaude" / "hooks" / "pre_tool_use_workflow_guard.py"
)


def _make_python_shim(tmp: Path) -> Path:
    """Thin python shim: redirect the guard -m invocation to the module file.

    Its path deliberately does not end in /.venv/bin/python3 so common.sh skips
    its background venv-repair path.
    """
    shim = tmp / "py-shim"
    shim.write_text(
        "#!/bin/bash\n"
        'if [[ "${1:-}" == "-m" && "${2:-}" == "omniclaude.hooks.pre_tool_use_workflow_guard" ]]; then\n'
        f'    exec "{sys.executable}" "{_GUARD_MODULE_FILE}"\n'
        "fi\n"
        f'exec "{sys.executable}" "$@"\n'
    )
    shim.chmod(0o755)
    return shim


def _make_omni_home(tmp: Path) -> Path:
    """Build a fake omni_home that is_omninode_repo() recognizes as an OmniNode repo."""
    omni_home = tmp / "omni_home"
    omni_home.mkdir(parents=True)
    (omni_home / "CLAUDE.md").write_text("OmniNode omniclaude registry\n")
    (omni_home / ".onex_state").mkdir()
    return omni_home


def _run(payload: dict, omni_home: Path, tmp: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    # Deliberately DO NOT set PROJECT_ROOT -- the wrapper must bind it.
    env.pop("PROJECT_ROOT", None)
    # All hooks on: neutralize any ambient ONEX_HOOKS_MASK that disables this bit.
    env.pop("ONEX_HOOKS_MASK", None)
    env["CLAUDE_PLUGIN_ROOT"] = str(_PLUGIN_ROOT)
    env["CLAUDE_PROJECT_DIR"] = str(omni_home)
    env["ONEX_REGISTRY_ROOT"] = str(omni_home)
    env["ONEX_STATE_DIR"] = str(tmp / "state")
    env["HOME"] = str(tmp / "home")
    (tmp / "home").mkdir(exist_ok=True)
    env["PLUGIN_PYTHON_BIN"] = str(_make_python_shim(tmp))
    return subprocess.run(
        ["bash", str(_SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env=env,
    )


@pytest.mark.unit
def test_canonical_clone_edit_is_blocked_closed() -> None:
    """Edit targeting a canonical clone must hard-block (exit 2) -- fail CLOSED."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        omni_home = _make_omni_home(tmp)
        (omni_home / "omniclaude" / "src").mkdir(parents=True)
        target = omni_home / "omniclaude" / "src" / "handler.py"
        result = _run(
            {
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": str(target),
                    "old_string": "a",
                    "new_string": "b",
                },
            },
            omni_home,
            tmp,
        )
    assert result.returncode == 2, (
        f"expected hard block (exit 2), got {result.returncode}. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    decision = json.loads(result.stdout)
    assert decision["decision"] == "block"
    assert "canonical clone" in decision["reason"].lower()


@pytest.mark.unit
def test_worktree_edit_is_allowed() -> None:
    """Edit inside omni_home/worktrees/... must pass through (exit 0)."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        omni_home = _make_omni_home(tmp)
        wt = omni_home / "worktrees" / "OMN-1" / "omniclaude" / "src"
        wt.mkdir(parents=True)
        target = wt / "handler.py"
        result = _run(
            {
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": str(target),
                    "old_string": "a",
                    "new_string": "b",
                },
            },
            omni_home,
            tmp,
        )
    assert result.returncode == 0, (
        f"worktree edit must be allowed, got exit {result.returncode}. "
        f"stderr={result.stderr!r}"
    )


@pytest.mark.unit
def test_common_sh_does_not_crash_without_project_root() -> None:
    """common.sh must not raise 'PROJECT_ROOT: unbound variable' under set -u.

    This is the fleet-wide fail-open landmine: any hook sourcing common.sh
    without binding PROJECT_ROOT would crash and be swallowed to exit 0.
    """
    common = _PLUGIN_ROOT / "hooks" / "scripts" / "common.sh"
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        shim = _make_python_shim(tmp)
        script = (
            "set -euo pipefail; "
            f'HOOKS_DIR="{_PLUGIN_ROOT}/hooks"; '
            f'PLUGIN_ROOT="{_PLUGIN_ROOT}"; '
            f'PLUGIN_PYTHON_BIN="{shim}"; '
            f'source "{common}"; '
            "echo SOURCED_OK"
        )
        result = subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env={"HOME": td, "PATH": os.environ.get("PATH", "")},
        )
    assert "unbound variable" not in result.stderr, (
        f"common.sh still crashes on unbound PROJECT_ROOT: {result.stderr!r}"
    )
    assert "SOURCED_OK" in result.stdout
