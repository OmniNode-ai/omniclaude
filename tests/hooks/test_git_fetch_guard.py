# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for the lane git-fetch arm of the shared-tree git guard (OMN-20495).

Written red first against a guard without the arm. A worktree shares its
canonical clone's refs and the canonical-clone sync keeps them current, so a
lane's own ``git fetch``/``pull``/``ls-remote``/``remote update`` against
GitHub is refused and pointed at ``canonical_clone_sync.py refresh``. Push,
non-GitHub remotes, calls outside a lane and the allowed processes pass. The
arm lives in ``shared_tree_git_guard.py`` (no new hook file: the operator's
2026-10-01 ruling and the canonical-file-shape ratchet).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from omnibase_core.validators.no_unguarded_git_subprocess import (
    scrub_git_location_env,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOKS_DIR = REPO_ROOT / "plugins" / "onex" / "hooks"
LIB_DIR = HOOKS_DIR / "lib"
HOOK_SCRIPT = HOOKS_DIR / "scripts" / "pre_tool_use_shared_tree_git_guard.sh"
ENTRYPOINT = HOOKS_DIR / "scripts" / "pre_tool_use_bash_guards.sh"
POLICY_PATH = (
    REPO_ROOT / "src/omniclaude/nodes/node_git_effect/git_admission_policy.json"
)
ENGINE = LIB_DIR / "canonical_clone_sync.py"


from omniclaude.nodes.node_git_effect.handlers import handler_git_admission as guard

GATE_BIT_NAME = guard.GATE_BIT_NAME
Policy = guard.Policy

pytestmark = pytest.mark.unit

_LANE_ENV = (
    "ONEX_LANE",
    "ONEX_LANE_ID",
    "ONEX_WORKTREES_ROOT",
    "OMNI_WORKTREES_DIR",
    "ONEX_PR_WATCHER",
    "ONEX_CANONICAL_CLONE_SYNC",
)


@pytest.fixture(autouse=True)
def _no_ambient_lane(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _LANE_ENV:
        monkeypatch.delenv(key, raising=False)


def evaluate_bash_command(
    command: str, policy: Policy, cwd: Path, env: dict[str, str]
) -> object:
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        from dataclasses import replace

        return guard.evaluate_bash_command(
            command, replace(policy, clone_sync_engine=str(ENGINE)), cwd, None, ()
        )
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


SLUG = "OmniNode-ai/omniclaude"


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        env={
            **scrub_git_location_env(os.environ),
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.invalid",
        },
    )


class Layout:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.registry = root / "registry"
        self.canonical = self.registry / "omniclaude"
        self.canonical.mkdir(parents=True)
        _git("init", "-q", "-b", "dev", cwd=self.canonical)
        _git("commit", "-q", "--allow-empty", "-m", "init", cwd=self.canonical)
        _git(
            "remote",
            "add",
            "origin",
            f"https://github.com/{SLUG}.git",
            cwd=self.canonical,
        )
        _git(
            "remote",
            "add",
            "lab",
            "ssh://labhost/srv/lab-run/repos/omniclaude.git",
            cwd=self.canonical,
        )
        _git("remote", "add", "scp", f"git@github.com:{SLUG}.git", cwd=self.canonical)
        _git("config", "remotes.everything", "lab origin", cwd=self.canonical)
        _git("config", "remotes.labonly", "lab", cwd=self.canonical)
        self.worktree = self.registry / "omni_worktrees" / "OMN-1" / "omniclaude"
        _git(
            "worktree",
            "add",
            "-q",
            "-b",
            "lane/one",
            str(self.worktree),
            cwd=self.canonical,
        )
        self.labrun = root / "home" / "lab-run" / "runs" / "rlane-x"
        self.labrun.parent.mkdir(parents=True)
        _git("worktree", "add", "-q", "--detach", str(self.labrun), cwd=self.canonical)
        self.local_remote = root / "mirror.git"
        self.local_remote.mkdir()


@pytest.fixture
def lay(tmp_path: Path) -> Layout:
    return Layout(tmp_path)


@pytest.fixture
def policy() -> Policy:
    return guard.load_policy(POLICY_PATH)


def _env(**extra: str) -> dict[str, str]:
    return dict(extra)


# --------------------------------------------------------------------------- #
# refusals
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "command",
    [
        "git fetch origin dev",
        "git fetch",
        "git fetch --prune origin",
        "git fetch -q origin +refs/heads/dev:refs/remotes/origin/dev",
        "git pull --ff-only origin dev",
        "git pull",
        "git ls-remote origin refs/heads/dev",
        f"git ls-remote --symref https://github.com/{SLUG} HEAD",
        "git ls-remote",
        "git remote update",
        "git remote update --prune everything",
        "git fetch --all",
        "git fetch scp",
        f"git fetch git@github.com:{SLUG}.git dev",
        "git -c protocol.version=2 fetch origin",
        "timeout 60 git fetch origin",
        "ONEX_PR_WATCHER=1 git fetch origin",
        "git status && git fetch origin dev",
        "git fetch --multiple lab origin",
    ],
)
def test_refuses_a_github_fetch_from_a_worktree(
    lay: Layout, policy: Policy, command: str
) -> None:
    decision = evaluate_bash_command(command, policy, lay.worktree, _env())
    assert decision.blocked, command
    assert "OMN-20495" in decision.reason
    assert f"{ENGINE} refresh" in decision.reason
    assert GATE_BIT_NAME in decision.reason


def test_refusal_names_the_repository_and_the_branch(
    lay: Layout, policy: Policy
) -> None:
    decision = evaluate_bash_command(
        "git fetch origin feature/x", policy, lay.worktree, _env()
    )
    assert decision.blocked
    assert f"refresh {SLUG} --wait --branch feature/x" in decision.reason
    assert "origin/<branch> as is" in decision.reason
    assert "\n" not in decision.reason


def test_refuses_a_cd_into_a_worktree_then_fetch(lay: Layout, policy: Policy) -> None:
    decision = evaluate_bash_command(
        f"cd {lay.worktree} && git fetch origin", policy, lay.root, _env()
    )
    assert decision.blocked


def test_refuses_a_dash_c_into_a_worktree(lay: Layout, policy: Policy) -> None:
    decision = evaluate_bash_command(
        f'git -C "{lay.worktree}" fetch origin dev', policy, lay.root, _env()
    )
    assert decision.blocked


def test_refuses_a_variable_dash_c_into_a_worktree(lay: Layout, policy: Policy) -> None:
    decision = evaluate_bash_command(
        'git -C "$WT" fetch origin', policy, lay.root, _env(WT=str(lay.worktree))
    )
    assert decision.blocked


def test_refuses_a_canonical_clone_fetch_typed_from_a_worktree(
    lay: Layout, policy: Policy
) -> None:
    """The cwd is the lane's: fetching the canonical clone from there is the
    same redundant traffic and the same race with the sync."""
    decision = evaluate_bash_command(
        f"git -C {lay.canonical} fetch -q origin dev", policy, lay.worktree, _env()
    )
    assert decision.blocked


def test_refuses_any_directory_when_onex_lane_is_set(
    lay: Layout, policy: Policy
) -> None:
    decision = evaluate_bash_command(
        "git fetch origin dev", policy, lay.canonical, _env(ONEX_LANE="some-lane")
    )
    assert decision.blocked


def test_refuses_in_a_remote_lane_run_directory(lay: Layout, policy: Policy) -> None:
    decision = evaluate_bash_command("git fetch origin", policy, lay.labrun, _env())
    assert decision.blocked


def test_refuses_under_a_declared_worktrees_root(
    tmp_path: Path, policy: Policy
) -> None:
    root = tmp_path / "wts"
    clone = root / "OMN-2" / "svc"
    clone.mkdir(parents=True)
    _git("init", "-q", cwd=clone)
    _git("remote", "add", "origin", f"https://github.com/{SLUG}", cwd=clone)
    decision = guard.evaluate_bash_command(
        "git fetch origin", policy, clone, None, (root.resolve(),)
    )
    assert decision.blocked


def test_refuses_an_unknown_remote_name_in_a_lane(lay: Layout, policy: Policy) -> None:
    decision = evaluate_bash_command("git fetch nosuch", policy, lay.worktree, _env())
    assert decision.blocked
    assert "nosuch" in decision.reason


def test_refuses_an_unexpandable_remote_word_in_a_lane(
    lay: Layout, policy: Policy
) -> None:
    decision = evaluate_bash_command(
        'git fetch "$(echo origin)"', policy, lay.worktree, _env()
    )
    assert decision.blocked


# --------------------------------------------------------------------------- #
# allows
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "command",
    [
        "git push origin HEAD",
        "git push -u origin lane/one",
        "git fetch lab dev",
        "git fetch labonly",
        "git fetch ssh://labhost/srv/lab-run/repos/omniclaude.git dev",
        "git fetch /tmp/some/mirror.git dev",
        "git remote -v",
        "git remote add other https://github.com/x/y",
        "git log origin/dev -1",
        "git merge --ff-only origin/dev",
        "echo git fetch origin",
        "grep -n 'git fetch origin' SKILL.md",
        f"python3 {ENGINE} refresh {SLUG} --wait",
        "cat <<'EOF'\ngit fetch origin\nEOF",
    ],
)
def test_allows_what_is_not_a_lane_github_fetch(
    lay: Layout, policy: Policy, command: str
) -> None:
    decision = evaluate_bash_command(command, policy, lay.worktree, _env())
    assert not decision.blocked, (command, decision.reason)


def test_allows_a_fetch_outside_a_lane_context(lay: Layout, policy: Policy) -> None:
    for command in ("git fetch origin dev", "git pull", "git ls-remote origin"):
        decision = evaluate_bash_command(command, policy, lay.canonical, _env())
        assert not decision.blocked, command


@pytest.mark.parametrize(
    "marker", [{"ONEX_PR_WATCHER": "1"}, {"ONEX_CANONICAL_CLONE_SYNC": "1"}]
)
def test_allows_the_watcher_and_the_sync(
    lay: Layout, policy: Policy, marker: dict[str, str]
) -> None:
    decision = evaluate_bash_command(
        "git fetch origin dev", policy, lay.worktree, _env(ONEX_LANE="x", **marker)
    )
    assert not decision.blocked


# --------------------------------------------------------------------------- #
# the shell wrapper and the Bash entrypoint
# --------------------------------------------------------------------------- #
def _run(
    script: Path, lay: Layout, command: str, cwd: Path, **extra: str
) -> subprocess.CompletedProcess[str]:
    state = lay.root / "state"
    env = {
        **scrub_git_location_env(os.environ),
        "OMNI_HOME": str(lay.registry),
        "ONEX_STATE_DIR": str(state),
        "CLAUDE_PLUGIN_ROOT": str(REPO_ROOT / "plugins" / "onex"),
        # The real checkout, as the git-stash guard tests do: repo_guard.sh
        # resolves is_omninode_repo from CLAUDE_PROJECT_DIR, and the fixture
        # clone carries no OmniNode marker. The payload cwd is what the guard
        # judges.
        "CLAUDE_PROJECT_DIR": str(REPO_ROOT),
        "OMNICLAUDE_MODE": "full",
        "PLUGIN_PYTHON_BIN": sys.executable,
        "ONEX_HOOKS_MASK": "",
        "HOME": str(lay.root / "home"),
        **extra,
    }
    for key in ("ONEX_LANE", "ONEX_LANE_ID", "ONEX_WORKTREES_ROOT", "ONEX_PR_WATCHER"):
        if key not in extra:
            env.pop(key, None)
    payload = {
        "hook_event_name": "PreToolUse",
        "session_id": "sess-git-fetch-guard",
        "cwd": str(cwd),
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }
    return subprocess.run(
        [str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
        timeout=60,
        check=False,
    )


@pytest.mark.parametrize(
    "script", [HOOK_SCRIPT, ENTRYPOINT], ids=["guard", "entrypoint"]
)
def test_hook_refuses_with_exit_two_and_logs_the_lane(
    lay: Layout, script: Path
) -> None:
    proc = _run(script, lay, "git fetch origin dev", lay.worktree, ONEX_LANE="lane-a")
    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    body = json.loads(proc.stdout)
    assert body["decision"] == "block"
    assert "OMN-20495" in body["reason"]
    log = (lay.root / "state" / "logs" / "git-fetch-guard.log").read_text()
    fields = log.strip().splitlines()[-1].split("\t")
    assert fields[1:5] == ["lane-a", "env", "git fetch", SLUG]
    assert fields[-1] == "refused"


@pytest.mark.parametrize(
    "script", [HOOK_SCRIPT, ENTRYPOINT], ids=["guard", "entrypoint"]
)
def test_hook_allows_push_silently(lay: Layout, script: Path) -> None:
    proc = _run(script, lay, "git push origin HEAD", lay.worktree)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert proc.stdout.strip() == ""


def test_hook_logs_the_worktree_as_the_lane_when_no_lane_is_named(lay: Layout) -> None:
    proc = _run(HOOK_SCRIPT, lay, "git pull", lay.worktree)
    assert proc.returncode == 2
    log = (lay.root / "state" / "logs" / "git-fetch-guard.log").read_text()
    fields = log.strip().splitlines()[-1].split("\t")
    assert fields[1:3] == ["OMN-1/omniclaude", "worktree"]


def test_hook_allows_a_non_lane_fetch(lay: Layout) -> None:
    proc = _run(HOOK_SCRIPT, lay, "git fetch origin dev", lay.canonical)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)


def test_hook_is_disabled_by_its_bit(lay: Layout) -> None:
    bit = 0x4000000000000  # SCOPE_GATE in lib/hook_bits.sh
    mask = hex(0xFFFFFFFFFFFFFFF & ~bit)
    proc = _run(
        HOOK_SCRIPT, lay, "git fetch origin dev", lay.worktree, ONEX_HOOKS_MASK=mask
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)


def test_hook_starts_no_interpreter_for_a_non_lane_fetch(lay: Layout) -> None:
    """Outside a lane the fetch vocabulary alone never reaches the core: a
    missing decision core would refuse, so an allow proves the pre-filter."""
    proc = _run(
        HOOK_SCRIPT,
        lay,
        "git fetch origin dev",
        lay.canonical,
        PLUGIN_PYTHON_BIN="/nonexistent/python",
        PATH="/usr/bin:/bin",
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
