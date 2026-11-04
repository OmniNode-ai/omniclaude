# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The worktree guard's decision core imports on a bare interpreter (OMN-19998).

The hook resolves ``PLUGIN_PYTHON_BIN`` first, and on a lab host that can be a
bare python3 with no omniclaude install. ``worktree_add_guard.py`` imported the
shared shell tokenizer from ``omniclaude`` with no source-root bootstrap, so it
died with ``ModuleNotFoundError`` and the hook refused every sanctioned
``git worktree add`` with "the worktree guard's decision core exited 1".

These run the core, and the registered hook script, on ``python -S`` with no
``PYTHONPATH``: a sanctioned destination is allowed and a stray one is still
refused with the guard's own reason, never the exit-1 refusal.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LIB = REPO_ROOT / "plugins" / "onex" / "hooks" / "lib"
GUARD_PY = LIB / "worktree_add_guard.py"
HOOK = (
    REPO_ROOT
    / "plugins"
    / "onex"
    / "hooks"
    / "scripts"
    / "pre_tool_use_worktree_guard.sh"
)
EXIT_1_REFUSAL = "decision core exited"


def _bare_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH"}}


def _payload(command: str) -> str:
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})


def _run_core(
    guard: Path, root: Path, command: str, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, "-S", str(guard), "--root", str(root), "--cwd", "/tmp"],
        input=_payload(command),
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=60,
    )


@pytest.mark.unit
@pytest.mark.parametrize("installed", [False, True])
def test_core_judges_on_bare_interpreter(tmp_path: Path, installed: bool) -> None:
    # An installed plugin copy has no src/ beside it: the registry clone is the source.
    env = _bare_env()
    guard = GUARD_PY
    if installed:
        copy = tmp_path / "plugin" / "plugins" / "onex" / "hooks" / "lib"
        copy.mkdir(parents=True)
        for f in LIB.glob("*.py"):
            (copy / f.name).write_bytes(f.read_bytes())
        guard = copy / GUARD_PY.name
        home = tmp_path / "home"
        home.mkdir()
        (home / "omniclaude").symlink_to(REPO_ROOT)
        env["OMNI_HOME"] = str(home)
    else:
        env.pop("OMNI_HOME", None)
    root = tmp_path / "omni_worktrees"

    allowed = _run_core(
        guard, root, f"git worktree add {root}/OMN-1/omniclaude -b b", env
    )
    assert "ModuleNotFoundError" not in allowed.stderr, allowed.stderr
    assert allowed.returncode == 0, allowed.stderr
    assert json.loads(allowed.stdout)["decision"] == "allow"

    refused = _run_core(guard, root, "git worktree add /elsewhere/r -b b", env)
    assert refused.returncode == 2, refused.stderr
    assert "Worktrees must be created under" in json.loads(refused.stdout)["reason"]


@pytest.mark.unit
def test_hook_on_bare_interpreter_allows_sanctioned_and_refuses_stray(
    tmp_path: Path,
) -> None:
    bare = tmp_path / "bin" / "py"
    bare.parent.mkdir()
    bare.write_text(f'#!/bin/sh\nexec "{sys.executable}" -S "$@"\n', encoding="utf-8")
    bare.chmod(0o755)
    home = tmp_path / "home"
    (home / ".onex_state").mkdir(parents=True)
    omni_home = tmp_path / "oh"
    (omni_home / "omni_worktrees").mkdir(parents=True)
    env = _bare_env()
    env.update(
        {
            "HOME": str(home),
            "ONEX_STATE_DIR": str(home / ".onex_state"),
            "OMNI_HOME": str(omni_home),
            "PLUGIN_PYTHON_BIN": str(bare),
            "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT / "plugins" / "onex"),
        }
    )
    for key in ("ONEX_WORKTREES_ROOT", "OMNI_WORKTREES_DIR", "ONEX_HOOKS_MASK"):
        env.pop(key, None)

    def run(command: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603
            ["bash", str(HOOK)],
            input=_payload(command),
            capture_output=True,
            text=True,
            env=env,
            check=False,
            timeout=60,
        )

    sanctioned = run(
        f"git worktree add {omni_home}/omni_worktrees/OMN-1/omniclaude -b b"
    )
    assert EXIT_1_REFUSAL not in sanctioned.stdout, sanctioned.stdout
    assert sanctioned.returncode == 0, sanctioned.stdout + sanctioned.stderr

    stray = run("git worktree add /elsewhere/r -b b")
    assert stray.returncode == 2, stray.stdout + stray.stderr
    reason = json.loads(stray.stdout)["reason"]
    assert "Worktrees must be created under" in reason
    assert EXIT_1_REFUSAL not in reason
