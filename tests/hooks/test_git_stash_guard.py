# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for the git-stash worktree admission gate (OMN-17334).

Written red first against an absent decision core (`git_stash_guard.py` and
`pre_tool_use_git_stash_guard.sh` did not exist before this ticket).

Every blocking case below reproduces the mechanism recorded in the ticket and
the rolling work ledger: git's stash is one repo-wide stack, so a stash
mutation run inside a WORKTREE (`.git` is a file pointing at the parent
clone) or inside a canonical clone directly under `$OMNI_HOME` (shared by
every concurrent lane) can pop or clobber a peer lane's uncommitted work.
There is deliberately no case admitting a stash mutation in either location
via some spelling of consent -- the ticket's own recommendation is that the
idiom has a non-destructive replacement, not that it needs an exception.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOKS_DIR = REPO_ROOT / "plugins" / "onex" / "hooks"
LIB_DIR = HOOKS_DIR / "lib"
HOOK_SCRIPT = HOOKS_DIR / "scripts" / "pre_tool_use_git_stash_guard.sh"
POLICY_PATH = HOOKS_DIR / "config" / "git_stash_guard_policy.json"
NAMESAKE_SCRIPT = "pre_tool_use_sweep_preflight.sh"

sys.path.insert(0, str(LIB_DIR))

from git_stash_guard import (  # noqa: E402
    GATE_BIT_NAME,
    Policy,
    PolicyError,
    evaluate_bash_command,
    load_policy,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def policy() -> Policy:
    return load_policy(POLICY_PATH)


def _make_worktree_clone(tmp_path: Path) -> tuple[Path, Path]:
    """A canonical clone plus one worktree of it, both git-usable.

    Returns (canonical_clone_dir, worktree_dir).
    """
    canonical = tmp_path / "canonical" / "omniclaude"
    canonical.parent.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(canonical)], check=True)
    subprocess.run(
        ["git", "-C", str(canonical), "config", "user.email", "t@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(canonical), "config", "user.name", "t"], check=True
    )
    subprocess.run(
        ["git", "-C", str(canonical), "commit", "-q", "--allow-empty", "-m", "init"],
        check=True,
    )
    worktree = tmp_path / "worktrees" / "wt"
    worktree.parent.mkdir(parents=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(canonical),
            "worktree",
            "add",
            str(worktree),
            "-b",
            "canary-branch",
        ],
        check=True,
        capture_output=True,
    )
    return canonical, worktree


def _make_plain_clone(tmp_path: Path) -> Path:
    repo = tmp_path / "elsewhere" / "some-repo"
    repo.parent.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "t@example.com"],
        check=True,
    )
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "--allow-empty", "-m", "init"],
        check=True,
    )
    return repo


# ---------------------------------------------------------------------------
# Policy loading
# ---------------------------------------------------------------------------


def test_policy_loads_and_declares_expected_vocabulary(policy: Policy) -> None:
    assert policy.ticket == "OMN-17334"
    assert "push" in policy.mutating_subcommands
    assert "pop" in policy.mutating_subcommands
    assert "apply" in policy.mutating_subcommands
    assert "drop" in policy.mutating_subcommands
    assert "save" in policy.mutating_subcommands
    assert "clear" in policy.mutating_subcommands
    assert "store" in policy.mutating_subcommands
    assert "branch" in policy.mutating_subcommands
    assert "list" in policy.safe_subcommands
    assert "show" in policy.safe_subcommands
    # Reads are never gated: no overlap between the two vocabularies.
    assert not (policy.mutating_subcommands & policy.safe_subcommands)


def test_missing_policy_file_raises(tmp_path: Path) -> None:
    with pytest.raises(PolicyError):
        load_policy(tmp_path / "does-not-exist.json")


def test_malformed_policy_json_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json")
    with pytest.raises(PolicyError):
        load_policy(bad)


# ---------------------------------------------------------------------------
# The four required behaviours (dispatch brief, verbatim)
# ---------------------------------------------------------------------------


def test_refuses_push_in_worktree(tmp_path: Path, policy: Policy) -> None:
    canonical, worktree = _make_worktree_clone(tmp_path)
    decision = evaluate_bash_command(
        "git stash push -- some_file.py", policy, cwd=worktree, omni_home_dir=None
    )
    assert decision.blocked
    assert "WORKTREE" in decision.reason
    assert "OMN-17334" in decision.reason
    assert policy.safe_alternative in decision.reason


def test_refuses_pop_in_canonical_omni_home_clone(
    tmp_path: Path, policy: Policy
) -> None:
    omni_home_dir = tmp_path / "omni_home_dir"
    omni_home_dir.mkdir()
    clone = omni_home_dir / "omniclaude"
    subprocess.run(["git", "init", "-q", str(clone)], check=True)
    subprocess.run(
        ["git", "-C", str(clone), "config", "user.email", "t@example.com"],
        check=True,
    )
    subprocess.run(["git", "-C", str(clone), "config", "user.name", "t"], check=True)
    subprocess.run(
        ["git", "-C", str(clone), "commit", "-q", "--allow-empty", "-m", "init"],
        check=True,
    )
    decision = evaluate_bash_command(
        "git stash pop", policy, cwd=clone, omni_home_dir=omni_home_dir
    )
    assert decision.blocked
    assert "canonical clone" in decision.reason
    assert "OMN-17334" in decision.reason


def test_allows_list(tmp_path: Path, policy: Policy) -> None:
    canonical, worktree = _make_worktree_clone(tmp_path)
    decision = evaluate_bash_command(
        "git stash list", policy, cwd=worktree, omni_home_dir=None
    )
    assert not decision.blocked


def test_allows_show(tmp_path: Path, policy: Policy) -> None:
    canonical, worktree = _make_worktree_clone(tmp_path)
    decision = evaluate_bash_command(
        "git stash show -p", policy, cwd=worktree, omni_home_dir=None
    )
    assert not decision.blocked


def test_allows_stash_in_a_non_omni_repo(tmp_path: Path, policy: Policy) -> None:
    repo = _make_plain_clone(tmp_path)
    omni_home_dir = tmp_path / "omni_home_dir"  # exists, but repo is not under it
    omni_home_dir.mkdir()
    decision = evaluate_bash_command(
        "git stash pop", policy, cwd=repo, omni_home_dir=omni_home_dir
    )
    assert not decision.blocked


# ---------------------------------------------------------------------------
# Additional shape coverage
# ---------------------------------------------------------------------------


def test_bare_git_stash_is_treated_as_push(tmp_path: Path, policy: Policy) -> None:
    canonical, worktree = _make_worktree_clone(tmp_path)
    decision = evaluate_bash_command(
        "git stash", policy, cwd=worktree, omni_home_dir=None
    )
    assert decision.blocked
    assert "`git stash push`" in decision.reason


def test_dash_c_target_is_checked_instead_of_cwd(
    tmp_path: Path, policy: Policy
) -> None:
    canonical, worktree = _make_worktree_clone(tmp_path)
    elsewhere = _make_plain_clone(tmp_path)
    # cwd is a harmless clone, but -C points at the worktree -- that must be
    # what gets checked, not the invoking cwd.
    decision = evaluate_bash_command(
        f"git -C {worktree} stash pop", policy, cwd=elsewhere, omni_home_dir=None
    )
    assert decision.blocked
    assert "WORKTREE" in decision.reason


def test_non_git_command_never_matches(tmp_path: Path, policy: Policy) -> None:
    canonical, worktree = _make_worktree_clone(tmp_path)
    decision = evaluate_bash_command("ls -la", policy, cwd=worktree, omni_home_dir=None)
    assert not decision.blocked


def test_pop_allowed_in_canonical_clone_when_omni_home_unset(
    tmp_path: Path, policy: Policy
) -> None:
    # Without OMNI_HOME resolvable, the canonical-clone condition cannot be
    # evaluated and is skipped -- this is a plain clone from the guard's
    # point of view, not a clone the guard can identify as canonical.
    clone = tmp_path / "omniclaude"
    subprocess.run(["git", "init", "-q", str(clone)], check=True)
    subprocess.run(
        ["git", "-C", str(clone), "config", "user.email", "t@example.com"],
        check=True,
    )
    subprocess.run(["git", "-C", str(clone), "config", "user.name", "t"], check=True)
    subprocess.run(
        ["git", "-C", str(clone), "commit", "-q", "--allow-empty", "-m", "init"],
        check=True,
    )
    decision = evaluate_bash_command(
        "git stash pop", policy, cwd=clone, omni_home_dir=None
    )
    assert not decision.blocked


# ---------------------------------------------------------------------------
# The bit borrow is faithful: registering the namesake must turn this red.
# ---------------------------------------------------------------------------


def test_borrowed_bit_namesake_is_unregistered() -> None:
    """SWEEP_PREFLIGHT is borrowed from pre_tool_use_sweep_preflight.sh.

    That borrow is only safe while the namesake stays unregistered -- if it
    were registered, `onex hooks disable SWEEP_PREFLIGHT` would silently
    disable two independent controls at once. This test is the pin: it must
    turn red the moment someone registers the namesake without giving this
    guard its own bit first.
    """
    assert GATE_BIT_NAME == "SWEEP_PREFLIGHT"
    hooks_json = json.loads((HOOKS_DIR / "hooks.json").read_text())
    all_commands = json.dumps(hooks_json)
    assert NAMESAKE_SCRIPT not in all_commands, (
        f"{NAMESAKE_SCRIPT} is now registered in hooks.json, which means the "
        f"{GATE_BIT_NAME} bit this guard borrows is no longer an uncontested "
        "borrow. Give pre_tool_use_git_stash_guard.sh its own bit, or pick a "
        "different unregistered namesake, before registering that script."
    )


# ---------------------------------------------------------------------------
# End-to-end shell wrapper (mirrors the hook_inventory canary, run directly)
# ---------------------------------------------------------------------------


def _run_hook(
    tmp_path: Path,
    command: str,
    cwd: Path | None = None,
    omni_home_dir: str | None = None,
) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    payload: dict[str, object] = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }
    if cwd is not None:
        payload["cwd"] = str(cwd)
    env = {
        "PATH": "/usr/bin:/bin:/opt/homebrew/bin",
        "HOME": str(home),
        "CLAUDE_PLUGIN_ROOT": str(HOOKS_DIR.parent),
        # Always the REAL omniclaude checkout, never the synthetic tmp repo
        # under test: is_omninode_repo() (repo_guard.sh) resolves its root
        # from CLAUDE_PROJECT_DIR and would otherwise pass this fixture
        # through untouched before the guard ever runs, matching how
        # test_hook_disable_control_canary.py's own harness sets it. The
        # payload's own `cwd` field -- not this env var -- is what
        # git_stash_guard.py resolves its target directory from.
        "CLAUDE_PROJECT_DIR": str(REPO_ROOT),
        "ONEX_HOOK_LOG": str(tmp_path / "hook.log"),
        "ONEX_STATE_DIR": str(tmp_path / "state"),
        "OMNICLAUDE_MODE": "full",
    }
    if omni_home_dir is not None:
        env["OMNI_HOME"] = omni_home_dir
    return subprocess.run(
        ["bash", str(HOOK_SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )


def test_shell_wrapper_refuses_pop_in_worktree(tmp_path: Path) -> None:
    canonical, worktree = _make_worktree_clone(tmp_path)
    result = _run_hook(tmp_path, "git stash pop", cwd=worktree)
    assert result.returncode == 2, (result.stdout, result.stderr)
    combined = result.stdout + result.stderr
    assert '"decision": "block"' in combined
    assert "OMN-17334" in combined


def test_shell_wrapper_allows_list(tmp_path: Path) -> None:
    canonical, worktree = _make_worktree_clone(tmp_path)
    result = _run_hook(tmp_path, "git stash list", cwd=worktree)
    assert result.returncode == 0, (result.stdout, result.stderr)


def test_shell_wrapper_allows_non_omni_repo(tmp_path: Path) -> None:
    repo = _make_plain_clone(tmp_path)
    omni_home_dir = tmp_path / "omni_home_dir"
    omni_home_dir.mkdir()
    result = _run_hook(
        tmp_path, "git stash pop", cwd=repo, omni_home_dir=str(omni_home_dir)
    )
    assert result.returncode == 0, (result.stdout, result.stderr)


def test_shell_wrapper_disabled_via_mask(tmp_path: Path) -> None:
    canonical, worktree = _make_worktree_clone(tmp_path)
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "git stash pop"},
        "cwd": str(worktree),
    }
    env = {
        "PATH": "/usr/bin:/bin:/opt/homebrew/bin",
        "HOME": str(home),
        "CLAUDE_PLUGIN_ROOT": str(HOOKS_DIR.parent),
        "CLAUDE_PROJECT_DIR": str(REPO_ROOT),
        "ONEX_HOOK_LOG": str(tmp_path / "hook.log"),
        "ONEX_STATE_DIR": str(tmp_path / "state"),
        "OMNICLAUDE_MODE": "full",
        "ONEX_HOOKS_MASK": "0x0",
    }
    result = subprocess.run(
        ["bash", str(HOOK_SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
