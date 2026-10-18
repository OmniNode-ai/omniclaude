# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Hook runners must not create artifacts the pre-push root gate rejects."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]


def test_wrapper_imports_root_module_without_leaving_bytecode(tmp_path):
    # Stand in for uv's command dispatch without resolving this repo's dependencies.
    binaries = tmp_path / "bin"
    binaries.mkdir()
    uv = binaries / "uv"
    uv.write_text('#!/bin/sh\n[ "$1" = run ] || exit 2\nshift\nexec "$@"\n')
    uv.chmod(0o755)
    (tmp_path / "conftest.py").write_text("IMPORTED = True\n")
    env = dict(os.environ)
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    env["PATH"] = f"{binaries}{os.pathsep}{env['PATH']}"
    result = subprocess.run(
        [
            "bash",
            str(_ROOT / "scripts/uv-run-worktree-safe.sh"),
            sys.executable,
            "-c",
            "import conftest; assert conftest.IMPORTED",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (tmp_path / "__pycache__").exists()


@pytest.mark.parametrize(
    "hook_id", ["ticket-refusal-reason", "git-command-segment-regression"]
)
def test_direct_pytest_hooks_disable_bytecode(hook_id):
    config = yaml.safe_load((_ROOT / ".pre-commit-config.yaml").read_text())
    hook = next(
        hook
        for repo in config["repos"]
        if repo["repo"] == "local"
        for hook in repo["hooks"]
        if hook["id"] == hook_id
    )
    args = shlex.split(hook["entry"])
    assert args[:2] == ["env", "PYTHONDONTWRITEBYTECODE=1"]
    assert "pytest" in args
