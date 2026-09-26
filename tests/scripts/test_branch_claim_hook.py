# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for OMN-18262 -- the pre-push refusal on a branch claimed by another lane.

THE INCIDENT. On 2026-09-12 at 14:17Z a lane from a peer session pushed three
commits to one repository's branch and four to another's, both under a ticket
held by a different lane's claim row. The claim row was the only ownership
record and it stopped nothing. Two lanes then fixed the same thing within an
hour and one of the two pull requests was closed unmerged.

THESE TESTS DRIVE A REAL `git push`, not the resolution behind it. That is
deliberate and it is the lesson of OMN-18260, where the defect that mattered most
-- the installer rewriting a placeholder inside its own guard pattern, so the
hook skipped the path it had just baked in -- was invisible to every test that
only read the script. A hook is a shell script run by git with git's environment
and git's PATH; nothing but running it that way proves it works.

DISABLED BY DEFAULT, TWO INDEPENDENT WAYS, and both are tested here:

  1. it is installed NOWHERE. Installation is its own explicit verb, separate
     from the lane-identity installer, so arming a clone is a decision somebody
     makes rather than a side effect of installing something else.
  2. even installed, it does NOTHING for a worktree that is not REGISTERED as a
     lane. Registration is the same mechanism the stamping hook uses, so opting
     in is one command a lane already runs, and a clone that gets the hook before
     its worktrees are registered refuses nobody.

That second property is the one that matters operationally: on 2026-09-13 a
leaked GIT_DIR pointed the lane-identity installer at the SHARED canonical-clone
hooks directory and every canonical clone began refusing commits from
unregistered worktrees for about ten minutes. A refusing hook whose default for
an unregistered worktree is REFUSE is that incident waiting to recur at fleet
scale. This one's default is silence.

Design of record: the OMN-18259 lane-identity and claim-index design, section 7.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from omnibase_core.validators.no_unguarded_git_subprocess import (
    scrub_git_location_env,
)

from scripts import lane_identity as li
from tests.scripts.conftest import link_canonical_module

REPO_ROOT = Path(__file__).resolve().parents[2]
TICKET = "OMN-9903"
BRANCH = "lane/omn-9903-scratch"
LEDGER_NAME = "SCRATCH_LEDGER.md"


def _stamp(offset_hours: float = 0.0) -> str:
    return (datetime.now(UTC) - timedelta(hours=offset_hours)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


@pytest.fixture
def scratch(tmp_path: Path) -> dict:
    """A clone with a real remote, one stamped commit, and a scratch store."""
    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", "-b", "main", str(remote)],
        check=True,
        env=scrub_git_location_env(os.environ),
    )
    repo = tmp_path / "clone"
    repo.mkdir()
    # `tmp_path` is this suite's registry, and the lane-identity module under
    # test is its canonical one. Since OMN-18800 the arming verb refuses to bake
    # any other copy's path into a hook, so a suite that arms anything has to
    # say which registry it is arming -- and saying `tmp_path` also stops the
    # ambient OMNI_HOME leaking in, which would aim the verb at the operator's
    # real workspace.
    link_canonical_module(tmp_path)
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"),
        "GIT_CONFIG_SYSTEM": str(tmp_path / "gitconfig-system"),
        li.WORKSPACE_ENV: str(tmp_path),
    }

    def run(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
            env=scrub_git_location_env(env),
        )

    run("init", "-q", "-b", "main")
    run("config", "user.email", "hook@example.com")
    run("config", "user.name", "hook")
    run("remote", "add", "origin", str(remote))
    (repo / "seed.txt").write_text("seed\n")
    run("add", "seed.txt")
    run("commit", "-q", "-m", "seed")
    run("push", "-q", "origin", "main")

    ledger = tmp_path / LEDGER_NAME
    ledger.write_text("# scratch claim store\n", encoding="utf-8")

    registry = tmp_path / "registry"
    registry.mkdir()

    return {
        "tmp": tmp_path,
        "repo": repo,
        "remote": remote,
        "ledger": ledger,
        "registry": registry,
        "env": env,
        "run": run,
    }


def _hook_env(scratch: dict) -> dict:
    return {
        **scratch["env"],
        "ONEX_LANE_REGISTRY_ROOT": str(scratch["registry"]),
        "ONEX_BRANCH_CLAIM_LEDGER": str(scratch["ledger"]),
        "ONEX_BRANCH_CLAIM_LEDGER_NAME": LEDGER_NAME,
        "ONEX_LANE_PYTHON": sys.executable,
    }


def _install(scratch: dict) -> Path:
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "branch_claim.py"),
            "install-hook",
            "--repo",
            str(scratch["repo"]),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=scratch["env"],
    )
    assert result.returncode == 0, result.stdout + result.stderr
    hook = scratch["repo"] / ".git" / "hooks" / "pre-push"
    assert hook.is_file(), result.stdout + result.stderr
    return hook


def _register(scratch: dict, lane: str) -> None:
    subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "lane_identity.py"),
            "--registry-root",
            str(scratch["registry"]),
            "register",
            "--lane",
            lane,
            "--ticket",
            TICKET,
            "--worktree",
            str(scratch["repo"]),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=scratch["env"],
    )


def _commit_on_branch(scratch: dict, lane: str | None, name: str = "work.txt") -> None:
    run = scratch["run"]
    current = run("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if current != BRANCH:
        run("checkout", "-q", "-b", BRANCH)
    (scratch["repo"] / name).write_text("work\n")
    run("add", name)
    message = f"feat({TICKET}): scratch work"
    if lane is not None:
        message += f"\n\n{li.LANE_TRAILER}: {lane}\n{li.SESSION_TRAILER}: {'3' * 32}\n"
    run("commit", "-q", "-m", message)


def _push(scratch: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "push", "origin", BRANCH],
        cwd=scratch["repo"],
        capture_output=True,
        text=True,
        check=False,
        env=scrub_git_location_env(_hook_env(scratch)),
    )


def _claim(scratch: dict, lane: str, *, hours_ago: float = 0.0) -> None:
    with scratch["ledger"].open("a", encoding="utf-8") as handle:
        handle.write(
            f"{_stamp(hours_ago)} | CLAIM | lane={lane} | tickets={TICKET} | taking it\n"
        )


def _release(scratch: dict, lane: str) -> None:
    with scratch["ledger"].open("a", encoding="utf-8") as handle:
        handle.write(
            f"{_stamp()} | RELEASE | lane={lane} | tickets={TICKET} | giving it up\n"
        )


# ---------------------------------------------------------------------------
# Disabled by default
# ---------------------------------------------------------------------------


def test_the_lane_identity_installer_does_not_install_this_hook(scratch: dict) -> None:
    """Arming a clone with a refusing pre-push hook must be its own decision, not
    a side effect of installing the stamping hook."""
    subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "lane_identity.py"),
            "--registry-root",
            str(scratch["registry"]),
            "install-hook",
            "--repo",
            str(scratch["repo"]),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=scratch["env"],
    )
    assert (scratch["repo"] / ".git" / "hooks" / "prepare-commit-msg").is_file()
    assert not (scratch["repo"] / ".git" / "hooks" / "pre-push").exists()


def test_an_unregistered_worktree_is_not_refused(scratch: dict) -> None:
    """The second, stronger half of disabled-by-default. A clone that receives
    this hook before its worktrees are registered refuses nobody -- which is the
    2026-09-13 leaked-GIT_DIR incident not recurring at fleet scale."""
    _install(scratch)
    # Deliberately the shape that WOULD be refused: the store says one lane holds
    # the ticket and the commit is stamped with a different one. If this passes
    # only because the two agreed, the test proves nothing about the gate --
    # confirmed by a falsification run in which removing the gate left this test
    # green until the two lanes were made to disagree.
    _claim(scratch, "holding-lane")
    _commit_on_branch(scratch, "another-lane")
    result = _push(scratch)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "holding-lane" not in result.stdout + result.stderr


# ---------------------------------------------------------------------------
# The refusal itself -- red on the 14:17Z shape, green control from the holder
# ---------------------------------------------------------------------------


def test_a_push_to_a_branch_held_by_another_lane_is_refused(scratch: dict) -> None:
    _install(scratch)
    _register(scratch, "this-lane")
    _claim(scratch, "holding-lane")
    _commit_on_branch(scratch, "this-lane")

    result = _push(scratch)
    assert result.returncode != 0, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert "holding-lane" in combined
    assert f"{LEDGER_NAME}:2" in combined
    assert "RELEASE" in combined
    assert "| CLAIM |" in combined
    assert "supersedes-claim=" in combined
    assert "| HANDOVER |" not in combined
    assert "| RECLAIM |" not in combined
    # And nothing reached the remote.
    refs = subprocess.run(
        ["git", "ls-remote", "--heads", str(scratch["remote"]), BRANCH],
        capture_output=True,
        text=True,
        check=True,
        env=scrub_git_location_env(os.environ),
    )
    assert refs.stdout.strip() == ""


def test_the_holder_pushes_the_same_commits_green(scratch: dict) -> None:
    """The green control for the test above. Without it, a hook that refused
    every push would score identically."""
    _install(scratch)
    _register(scratch, "holding-lane")
    _claim(scratch, "holding-lane")
    _commit_on_branch(scratch, "holding-lane")

    result = _push(scratch)
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_release_row_clears_the_refusal(scratch: dict) -> None:
    """The risk this ticket names: a refusing hook must not block legitimate
    handover. One row, written by the holder, and the push goes through."""
    _install(scratch)
    _register(scratch, "this-lane")
    _claim(scratch, "holding-lane")
    _commit_on_branch(scratch, "this-lane")
    assert _push(scratch).returncode != 0

    _release(scratch, "holding-lane")
    result = _push(scratch)
    assert result.returncode == 0, result.stdout + result.stderr


def test_an_unclaimed_branch_is_not_refused(scratch: dict) -> None:
    _install(scratch)
    _register(scratch, "this-lane")
    _commit_on_branch(scratch, "this-lane")
    assert _push(scratch).returncode == 0


def test_a_stale_claim_does_not_refuse(scratch: dict) -> None:
    _install(scratch)
    _register(scratch, "this-lane")
    _claim(scratch, "holding-lane", hours_ago=48)
    _commit_on_branch(scratch, "this-lane")
    assert _push(scratch).returncode == 0


def test_an_unstamped_commit_is_reported_but_not_refused(scratch: dict) -> None:
    """Measured 2026-09-13, no commit in the fleet carries a lane trailer.
    Refusing on an absent one would be a fleet-wide push freeze on install day,
    which is how a gate gets routed around rather than obeyed."""
    _install(scratch)
    _register(scratch, "this-lane")
    _claim(scratch, "holding-lane")
    _commit_on_branch(scratch, None)

    result = _push(scratch)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "no resolvable lane identity" in result.stdout + result.stderr


# ---------------------------------------------------------------------------
# The pushes that are not branch pushes, and the ones git writes itself
# ---------------------------------------------------------------------------


def test_a_second_push_onto_an_existing_remote_branch_is_still_checked(
    scratch: dict,
) -> None:
    """The new-branch range and the update range are computed differently, so the
    update path needs its own proof -- the 14:17Z push was an update, not a
    branch creation."""
    _install(scratch)
    _register(scratch, "this-lane")
    _commit_on_branch(scratch, "this-lane")
    assert _push(scratch).returncode == 0

    _claim(scratch, "holding-lane")
    _commit_on_branch(scratch, "this-lane", name="more.txt")
    result = _push(scratch)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "holding-lane" in result.stdout + result.stderr


def test_deleting_a_branch_is_not_refused(scratch: dict) -> None:
    """A deletion pushes no commits. Refusing it would make the hook fire on the
    one operation that cannot carry a lane."""
    _install(scratch)
    _register(scratch, "this-lane")
    _commit_on_branch(scratch, "this-lane")
    assert _push(scratch).returncode == 0

    _claim(scratch, "holding-lane")
    result = subprocess.run(
        ["git", "push", "origin", "--delete", BRANCH],
        cwd=scratch["repo"],
        capture_output=True,
        text=True,
        check=False,
        env=scrub_git_location_env(_hook_env(scratch)),
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_branch_with_no_ticket_in_its_name_is_not_refused(scratch: dict) -> None:
    _install(scratch)
    _register(scratch, "this-lane")
    run = scratch["run"]
    run("checkout", "-q", "-b", "chore/no-ticket-here")
    (scratch["repo"] / "chore.txt").write_text("chore\n")
    run("add", "chore.txt")
    run("commit", "-q", "-m", "chore: something")
    _claim(scratch, "holding-lane")
    result = subprocess.run(
        ["git", "push", "origin", "chore/no-ticket-here"],
        cwd=scratch["repo"],
        capture_output=True,
        text=True,
        check=False,
        env=scrub_git_location_env(_hook_env(scratch)),
    )
    assert result.returncode == 0, result.stdout + result.stderr


# ---------------------------------------------------------------------------
# Fail-closed, and the installer guard that stopped a fleet incident
# ---------------------------------------------------------------------------


def test_an_unreadable_claim_store_refuses_the_push(scratch: dict) -> None:
    """A store it cannot read yields no holders, and no holders reads exactly
    like every branch being unclaimed. The hook must refuse, not skip."""
    _install(scratch)
    _register(scratch, "this-lane")
    _commit_on_branch(scratch, "this-lane")

    env = _hook_env(scratch)
    env["ONEX_BRANCH_CLAIM_LEDGER"] = str(scratch["tmp"] / "no-such-store.md")
    result = subprocess.run(
        ["git", "push", "origin", BRANCH],
        cwd=scratch["repo"],
        capture_output=True,
        text=True,
        check=False,
        env=scrub_git_location_env(env),
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert "no-such-store.md" in result.stdout + result.stderr


def test_the_installer_refuses_a_hooks_directory_outside_the_repo(
    scratch: dict, tmp_path: Path
) -> None:
    """The 2026-09-13 incident, pinned. An inherited GIT_DIR pointed the
    lane-identity installer at the SHARED canonical-clone hooks directory and
    every canonical clone began refusing commits until the file was removed by
    hand. The pre-push installer must not ship a weaker copy of that check."""
    shared = tmp_path / "shared-hooks"
    shared.mkdir()
    subprocess.run(
        ["git", "config", "core.hooksPath", str(shared)],
        cwd=scratch["repo"],
        check=True,
        capture_output=True,
        text=True,
        env=scrub_git_location_env(scratch["env"]),
    )
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "branch_claim.py"),
            "install-hook",
            "--repo",
            str(scratch["repo"]),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=scratch["env"],
    )
    # OMN-18273: the refusal is kept but made structural. The installer resolves
    # `<git-common-dir>/hooks` rather than following core.hooksPath, so the
    # shared directory is never written -- and the install is reported NOT
    # REACHABLE (exit 4) instead of succeeding silently, because git will not
    # dispatch the file until the shared directory carries a chaining entry.
    # Asserting exit 2 here was what made the mechanism uninstallable on the
    # real workspace, where every canonical clone sets core.hooksPath.
    assert result.returncode == 4, result.stdout + result.stderr
    assert "NOT REACHABLE" in result.stderr
    assert not (shared / "pre-push").exists()
    assert (scratch["repo"] / ".git" / "hooks" / "pre-push").is_file()


def test_the_installed_hook_carries_no_unreplaced_placeholder(scratch: dict) -> None:
    """OMN-18260's most expensive defect: the installer rewrote the placeholder
    inside its own guard pattern, so the hook skipped the path it had just baked
    in, and no test that merely READ the script could see it."""
    hook = _install(scratch)
    body = hook.read_text(encoding="utf-8")
    assert "@BRANCH_CLAIM_PATH@" not in body
    assert str(REPO_ROOT / "scripts" / "branch_claim.py") in body
    assert os.access(hook, os.X_OK)


def test_the_hook_is_syntactically_valid_shell() -> None:
    source = REPO_ROOT / "scripts" / "hooks" / "pre-push-branch-claim"
    assert source.is_file()
    result = subprocess.run(
        ["bash", "-n", str(source)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_this_repository_has_no_branch_claim_pre_push_installed() -> None:
    """Shipped disabled: installed nowhere, including here. Rolling it out across
    the canonical clones is OMN-18288's sequenced sweep, deliberately not this
    change.

    Two places are checked, because this workspace points its clones at a SHARED
    hooks directory and the interesting one is the shared directory -- a pre-push
    hook there would arm every repository that shares it. Reading only the
    repository's own git directory would return a clean answer about the place
    the incident did not happen.
    """
    candidates = []
    try:
        candidates.append(li.own_hooks_dir(REPO_ROOT) / "pre-push")
    except li.SharedHooksDirectory:
        pass
    configured = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-path", "hooks"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
        env=scrub_git_location_env(os.environ),
    ).stdout.strip()
    candidates.append(Path(configured) / "pre-push")
    candidates.append(Path(REPO_ROOT / ".git" / "hooks" / "pre-push"))

    for installed in candidates:
        if installed.is_file():
            assert "branch_claim.py" not in installed.read_text(encoding="utf-8"), (
                f"{installed} already arms the branch-claim refusal; rollout is "
                "OMN-18288, not this change"
            )
