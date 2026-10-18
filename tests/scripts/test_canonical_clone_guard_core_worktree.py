# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The user-level canonical-clone guard refuses core.worktree in a canonical clone (OMN-17427).

On 2026-10-18 a lane run set ``core.worktree`` in a canonical clone's
``.git/config`` to its own run directory. Every git command on the clone then
read the wrong tree: ``git status`` printed clean over a stale checkout, a
convergence reset the lane's directory instead of the clone, and a plugin tick
that put the clone's ``src`` on ``sys.path`` crashed for every session.

The live mechanism, reproduced with git itself: a lane exports
``GIT_DIR=<clone>/.git/worktrees/<n>`` and ``GIT_WORK_TREE=<n's tree>``; any
``git init`` run then writes ``core.worktree`` into the clone's SHARED config.

Driven exactly as Claude Code drives the hook: a subprocess with the hook JSON
on stdin and a scratch environment. Each ``test_control_*`` shows the same call
allowed where it is harmless, so a denial is known to come from the rule.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD = REPO_ROOT / "scripts" / "user-hooks" / "canonical-clone-guard.py"


@pytest.fixture
def registry(tmp_path: Path) -> Path:
    home = tmp_path / "registry"
    (home / "some_repo" / ".git" / "worktrees" / "lane").mkdir(parents=True)
    (home / "some_repo" / "src").mkdir()
    (home / "omni_worktrees" / "OMN-1" / "some_repo").mkdir(parents=True)
    (tmp_path / "lane_run").mkdir()
    return home


def _decide(
    home: Path, command: str, cwd: Path, extra_env: dict[str, str] | None = None
) -> tuple[str, str]:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home.parent),
        "OMNI_HOME": str(home),
    }
    env.update(extra_env or {})
    proc = subprocess.run(
        [sys.executable, str(GUARD)],
        input=json.dumps(
            {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}
        ),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    if not proc.stdout.strip():
        return "allow", ""
    out = json.loads(proc.stdout)["hookSpecificOutput"]
    return out["permissionDecision"], out["permissionDecisionReason"]


def _denied(
    home: Path, command: str, cwd: Path, extra_env: dict[str, str] | None = None
) -> str:
    decision, reason = _decide(home, command, cwd, extra_env)
    assert decision == "deny", command
    return reason


def _allowed(
    home: Path, command: str, cwd: Path, extra_env: dict[str, str] | None = None
) -> None:
    decision, reason = _decide(home, command, cwd, extra_env)
    assert decision == "allow", (command, reason)


@pytest.mark.unit
def test_config_core_worktree_write_denied_in_canonical(registry: Path) -> None:
    clone = registry / "some_repo"
    reason = _denied(registry, "git config core.worktree /somewhere/else", clone)
    assert "core.worktree" in reason and "some_repo" in reason
    assert "--unset core.worktree" in reason  # the repair stays named


@pytest.mark.unit
@pytest.mark.parametrize(
    "command",
    [
        "git config core.worktree /somewhere/else",
        "git config --local core.worktree /somewhere/else",
        "git config CORE.WORKTREE /somewhere/else",
        "git config --add core.worktree /somewhere/else",
        "git -C {clone} config core.worktree /somewhere/else",
        "cd {clone} && git config core.worktree /somewhere/else",
        "git config --file {clone}/.git/config core.worktree /somewhere/else",
    ],
)
def test_every_spelling_of_the_write_is_denied(
    registry: Path, tmp_path: Path, command: str
) -> None:
    clone = registry / "some_repo"
    _denied(registry, command.format(clone=clone), clone)


@pytest.mark.unit
def test_control_config_write_in_a_worktree_and_reads_and_unset_in_canonical_allowed(
    registry: Path,
) -> None:
    clone = registry / "some_repo"
    _allowed(
        registry,
        "git config core.worktree /x",
        registry / "omni_worktrees/OMN-1/some_repo",
    )
    _allowed(registry, "git config --get core.worktree", clone)
    _allowed(registry, "git config core.worktree", clone)
    _allowed(registry, "git config --list", clone)
    _allowed(registry, "git config --unset core.worktree", clone)  # the repair
    _allowed(registry, "git config user.name x", clone)  # another key


@pytest.mark.unit
@pytest.mark.parametrize(
    "command",
    [
        "git --work-tree={lane} status",
        "git --work-tree {lane} status",
        "git -C {clone} --work-tree={lane} diff",
        "git --git-dir={clone}/.git --work-tree={lane} log",
        "git --git-dir {clone}/.git --work-tree {lane} log",
        "GIT_WORK_TREE={lane} git -C {clone} status",
    ],
)
def test_work_tree_elsewhere_denied_in_canonical(
    registry: Path, tmp_path: Path, command: str
) -> None:
    clone = registry / "some_repo"
    reason = _denied(
        registry, command.format(clone=clone, lane=tmp_path / "lane_run"), clone
    )
    assert "work tree is the clone itself" in reason


@pytest.mark.unit
def test_control_work_tree_naming_the_clone_or_a_worktree_allowed(
    registry: Path, tmp_path: Path
) -> None:
    clone = registry / "some_repo"
    worktree = registry / "omni_worktrees/OMN-1/some_repo"
    lane = tmp_path / "lane_run"
    # a work tree equal to the clone is what git assumes anyway (the landing reader spells it)
    _allowed(
        registry,
        f"git --git-dir={clone}/.git --work-tree={clone} diff origin/main",
        tmp_path,
    )
    _allowed(registry, f"git -C {clone} --work-tree={clone} status", tmp_path)
    # outside a canonical clone the option is not this guard's business
    _allowed(registry, f"git -C {worktree} --work-tree={lane} status", tmp_path)
    _allowed(
        registry, f"git --git-dir={worktree}/.git --work-tree={lane} status", tmp_path
    )
    _allowed(registry, f"git -C {clone} status", tmp_path)


@pytest.mark.unit
def test_the_live_mechanism_git_init_under_a_linked_gitdir_with_a_work_tree_denied(
    registry: Path, tmp_path: Path
) -> None:
    """The reproduced cause: GIT_DIR a linked worktree's git dir, GIT_WORK_TREE its tree, then `git init`."""
    clone = registry / "some_repo"
    linked = clone / ".git" / "worktrees" / "lane"
    lane = tmp_path / "lane_run"
    reason = _denied(
        registry,
        f"export GIT_DIR={linked} GIT_WORK_TREE={lane}; git -C {tmp_path} init -q",
        tmp_path,
    )
    assert "git init" in reason
    _denied(registry, f"GIT_DIR={linked} GIT_WORK_TREE={lane} git init", tmp_path)
    _denied(
        registry,
        "git init",
        tmp_path,
        extra_env={"GIT_DIR": str(linked), "GIT_WORK_TREE": str(lane)},
    )
    # the control: the same exports drive an ordinary read or commit-free command in the lane's own tree
    _allowed(
        registry,
        f"export GIT_DIR={linked} GIT_WORK_TREE={lane}; git status -s",
        tmp_path,
    )
    _allowed(
        registry, f"export GIT_DIR={linked}; git init", tmp_path
    )  # no work tree set: nothing is written
