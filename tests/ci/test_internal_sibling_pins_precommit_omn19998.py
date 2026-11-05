# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-19998: internal-sibling-pins is enforced by a pre-commit hook as well as the CI job.

RULING 2026-11-02T15:20:36Z relaxed the check to accept a published PyPI release behind a newer dev
merge tag. The handler is wired in CI (job ``internal-sibling-pins`` under Quality Gate); a mechanism
needs the pre-commit side too, so a refused pin stops at commit time. The ``check-internal-sibling-pins``
hook of omnibase_core runs a different validator (first-party refs), not this handler.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[2]
MODULE = "omniclaude.handlers.handler_internal_sibling_pins"


def _hook() -> dict:
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text())
    hooks = [
        hook
        for repo in config["repos"]
        if repo["repo"] == "local"
        for hook in repo["hooks"]
        if MODULE in hook.get("entry", "")
    ]
    assert len(hooks) == 1, "one local pre-commit hook runs the sibling-pins handler"
    return hooks[0]


def test_a_local_hook_runs_the_handler_on_the_lockfile() -> None:
    hook = _hook()
    assert "--head-lock uv.lock" in hook["entry"]
    assert "pre-commit" in hook["stages"]
    for path in ("uv.lock", "src/omniclaude/handlers/handler_internal_sibling_pins.py"):
        assert path.replace(".", r"\.") in hook["files"], path


def test_the_hook_entry_passes_on_the_checked_in_lock() -> None:
    entry = shlex.split(
        _hook()["entry"].replace(
            "bash scripts/uv-run-worktree-safe.sh python", sys.executable
        )
    )
    result = subprocess.run(
        entry,
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": "src", "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_the_hook_refuses_a_release_pin_that_is_not_a_published_pypi_release(
    tmp_path: Path,
) -> None:
    lock = tmp_path / "uv.lock"
    lock.write_text(
        '[[package]]\nname = "omnibase-core"\nversion = "0.47.1"\n'
        'source = { git = "https://github.com/OmniNode-ai/omnibase_core.git?tag=v0.47.1#abc" }\n'
    )
    result = subprocess.run(
        [sys.executable, "-m", MODULE, "--head-lock", str(lock)],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": "src", "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
