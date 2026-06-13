# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for pre_tool_use_plan_existence_gate.sh OCC-branch exemption (OMN-13139).

The Plan Gate blocks Edit/Write on ticket-shaped branches (``/omn-NNNN-``) when no
file exists under ``<repo_root>/docs/plans/``. OCC evidence branches
(``jonah/omn-XXXX-occ``) record verification evidence for a fix implemented in
another repo and live in ``onex_change_control`` (which has no ``docs/plans/``),
so the gate must exempt them — otherwise it blocks the very Write that would
create the first plan (no bootstrap path).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

_HOOK = (
    Path(__file__).parent.parent.parent
    / "plugins"
    / "onex"
    / "hooks"
    / "scripts"
    / "pre_tool_use_plan_existence_gate.sh"
)

_STDIN = json.dumps({"tool_name": "Write", "tool_input": {"file_path": "x.py"}})


def _init_repo(root: Path, branch: str) -> None:
    """Create a git repo recognized as an OmniNode repo, on ``branch``."""
    (root / ".onex_state").mkdir()  # is_omninode_repo marker
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    (root / "seed.txt").write_text("seed\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=root, check=True)
    subprocess.run(["git", "checkout", "-q", "-b", branch], cwd=root, check=True)


def _run_hook(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(_HOOK)],
        cwd=root,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "CLAUDE_PROJECT_DIR": str(root),
            "HOME": str(root),  # block path writes a log under $HOME/.claude
        },
        input=_STDIN,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.unit
def test_occ_branch_is_exempt(tmp_path: Path) -> None:
    """An OCC evidence branch passes through even with no docs/plans/."""
    _init_repo(tmp_path, "jonah/omn-13138-occ")
    result = _run_hook(tmp_path)
    assert result.returncode == 0, result.stderr
    assert '"decision"' not in result.stdout  # not a block envelope
    assert "tool_name" in result.stdout  # stdin echoed through


@pytest.mark.unit
def test_normal_ticket_branch_without_plan_still_blocks(tmp_path: Path) -> None:
    """A normal ticket branch with no docs/plans/ is still blocked (gate intact)."""
    _init_repo(tmp_path, "jonah/omn-9999-some-feature")
    result = _run_hook(tmp_path)
    assert result.returncode == 2
    assert '"decision": "block"' in result.stdout


@pytest.mark.unit
def test_normal_ticket_branch_with_plan_passes(tmp_path: Path) -> None:
    """A normal ticket branch with a docs/plans/ file passes through."""
    _init_repo(tmp_path, "jonah/omn-9999-some-feature")
    plans = tmp_path / "docs" / "plans"
    plans.mkdir(parents=True)
    (plans / "plan.md").write_text("# plan\n")
    result = _run_hook(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "tool_name" in result.stdout


@pytest.mark.unit
def test_non_ticket_branch_passes(tmp_path: Path) -> None:
    """A non-ticket branch is never gated."""
    _init_repo(tmp_path, "main-ish")
    result = _run_hook(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "tool_name" in result.stdout
