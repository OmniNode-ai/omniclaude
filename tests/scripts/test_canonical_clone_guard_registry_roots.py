# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The user-level canonical-clone guard covers every registry root (OMN-19388).

The registry is moving from the directory ``$OMNI_HOME`` names to a second root
that holds a fresh canonical clone of every repository, while ``OMNI_HOME``
stays unchanged until the move is finished. The guard judged a path only
against ``$OMNI_HOME``, so an Edit or a ``git commit`` in a second-root clone
was allowed. ``ONEX_REGISTRY_ROOTS`` names the extra roots, and the
canonical-clone git hooks read the same setting.

Driven exactly as Claude Code drives the hook: a subprocess with the hook JSON
on stdin and a scratch environment, so nothing touches the real machine. Each
``test_control_*`` shows the same call allowed with the setting absent, so a
denial is known to come from the setting.
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
def roots(tmp_path: Path) -> tuple[Path, Path]:
    home = tmp_path / "omni_home"
    new_root = tmp_path / "new_registry"
    for root in (home, new_root):
        (root / "some_repo" / ".git").mkdir(parents=True)
        (root / "some_repo" / "src").mkdir()
        (root / "omni_worktrees" / "OMN-1" / "some_repo").mkdir(parents=True)
    return home, new_root


def _guard(
    home: Path,
    tool_name: str,
    tool_input: dict[str, object],
    cwd: Path,
    registry_roots: str | None,
) -> tuple[str, str]:
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(home.parent)}
    env["OMNI_HOME"] = str(home)
    if registry_roots is not None:
        env["ONEX_REGISTRY_ROOTS"] = registry_roots
    proc = subprocess.run(
        [sys.executable, str(GUARD)],
        input=json.dumps(
            {"tool_name": tool_name, "tool_input": tool_input, "cwd": str(cwd)}
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


def _edit(path: Path) -> tuple[str, dict[str, object]]:
    return "Edit", {"file_path": str(path), "old_string": "a", "new_string": "b"}


@pytest.mark.unit
def test_control_second_root_edit_allowed_without_the_setting(
    roots: tuple[Path, Path],
) -> None:
    home, new_root = roots
    tool, payload = _edit(new_root / "some_repo" / "src" / "x.py")

    decision, _ = _guard(home, tool, payload, new_root, None)

    assert decision == "allow"


@pytest.mark.unit
def test_second_root_edit_denied(roots: tuple[Path, Path]) -> None:
    home, new_root = roots
    tool, payload = _edit(new_root / "some_repo" / "src" / "x.py")

    decision, reason = _guard(home, tool, payload, new_root, f"{home}:{new_root}")

    assert decision == "deny"
    assert "some_repo" in reason
    assert str(new_root) in reason


@pytest.mark.unit
def test_second_root_git_commit_denied(roots: tuple[Path, Path]) -> None:
    home, new_root = roots
    clone = new_root / "some_repo"

    decision, reason = _guard(
        home, "Bash", {"command": "git commit -m x"}, clone, str(new_root)
    )

    assert decision == "deny"
    assert "some_repo" in reason


@pytest.mark.unit
def test_control_second_root_git_commit_allowed_without_the_setting(
    roots: tuple[Path, Path],
) -> None:
    home, new_root = roots

    decision, _ = _guard(
        home, "Bash", {"command": "git commit -m x"}, new_root / "some_repo", None
    )

    assert decision == "allow"


@pytest.mark.unit
def test_git_dash_c_into_a_second_root_clone_denied(roots: tuple[Path, Path]) -> None:
    home, new_root = roots
    command = f"git -C {new_root / 'some_repo'} checkout -b scratch"

    decision, _ = _guard(home, "Bash", {"command": command}, home, str(new_root))

    assert decision == "deny"


@pytest.mark.unit
def test_worktree_add_from_a_second_root_clone_allowed(
    roots: tuple[Path, Path],
) -> None:
    """The sanctioned escape: link a worktree under $OMNI_HOME/omni_worktrees."""
    home, new_root = roots
    command = (
        f"git -C {new_root / 'some_repo'} worktree add "
        f"{home / 'omni_worktrees' / 'OMN-2' / 'some_repo'} -b b"
    )

    decision, _ = _guard(home, "Bash", {"command": command}, home, str(new_root))

    assert decision == "allow"


@pytest.mark.unit
def test_worktree_edit_and_commit_allowed(roots: tuple[Path, Path]) -> None:
    home, new_root = roots
    worktree = home / "omni_worktrees" / "OMN-1" / "some_repo"
    tool, payload = _edit(worktree / "x.py")
    registry_roots = f"{home}:{new_root}"

    assert _guard(home, tool, payload, worktree, registry_roots)[0] == "allow"
    assert (
        _guard(home, "Bash", {"command": "git commit -m x"}, worktree, registry_roots)[
            0
        ]
        == "allow"
    )


@pytest.mark.unit
def test_first_root_still_guarded_with_the_setting(roots: tuple[Path, Path]) -> None:
    home, new_root = roots
    tool, payload = _edit(home / "some_repo" / "src" / "x.py")

    decision, _ = _guard(home, tool, payload, home, str(new_root))

    assert decision == "deny"


@pytest.mark.unit
def test_a_root_own_files_are_not_guarded(roots: tuple[Path, Path]) -> None:
    home, new_root = roots
    tool, payload = _edit(new_root / "README.md")

    decision, _ = _guard(home, tool, payload, new_root, str(new_root))

    assert decision == "allow"


@pytest.mark.unit
@pytest.mark.parametrize("bad", ["relative/root", "", "{missing}"])
def test_a_malformed_setting_denies_what_it_would_judge(
    roots: tuple[Path, Path], tmp_path: Path, bad: str
) -> None:
    home, _new_root = roots
    value = bad.format(missing=tmp_path / "does-not-exist")
    tool, payload = _edit(tmp_path / "anywhere.txt")

    decision, reason = _guard(home, tool, payload, tmp_path, value)

    assert decision == "deny"
    assert "ONEX_REGISTRY_ROOTS" in reason


@pytest.mark.unit
def test_a_malformed_setting_leaves_non_git_bash_reachable(
    roots: tuple[Path, Path], tmp_path: Path
) -> None:
    """The remedy -- editing the environment with a shell command -- must stay
    possible, or a typo would lock the session out of its own fix."""
    home, _new_root = roots

    decision, _ = _guard(home, "Bash", {"command": "ls"}, tmp_path, "relative/root")

    assert decision == "allow"
